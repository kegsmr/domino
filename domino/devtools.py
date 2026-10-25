"""Developer tools, only in debug mode: the error page shown when a page fails to render, the
frames and component stack behind the browser's error overlay, the component inspector's data
(served to debug.js) and a few warnings when the app starts. Outside debug mode none of it runs:
pages render exactly as they would without it and its URLs answer 404.
"""

import gc
import inspect
import linecache
import os
import re
import sys
import traceback
import types

from flask import Response, abort, jsonify, request
from markupsafe import escape

from . import optimistic
from .core import Element
from .reactive import Collection, State


# Lines of source shown around each frame: the app's own, and libraries' (collapsed)
CONTEXT = 3
LIBRARY_CONTEXT = 1

# Longest repr() the inspector shows for a value
MAX_REPR = 300

DOMINO_DIR = os.path.dirname(os.path.abspath(__file__))

# Folders under the app's that hold other people's code
LIBRARY_FOLDERS = {"site-packages", "dist-packages", ".venv", "venv", "env", "node_modules", ".domino"}

TEMPLATE_LINE = re.compile(r"^line (\d+): ")

_script = None


def add_routes(app):
	"""/_domino/debug.js and the inspector's data, both 404 outside debug mode."""

	def script():

		global _script

		if not app.debug:
			abort(404)
		if _script is None:
			with open(os.path.join(DOMINO_DIR, "debug.js"), encoding="utf-8") as file:
				_script = file.read()

		return Response(_script, mimetype="text/javascript", headers={"Cache-Control": "no-store"})

	def data(what):

		if not app.debug or what not in ("components", "inspect"):
			abort(404)

		# Only the page itself knows its id, and a component is only shown to the page showing it.
		# The header can't come from another site's form (and a fetch with it needs a CORS preflight)
		page = app._get_page(request.headers.get("X-Domino-Page"))
		if page is None:
			return jsonify({"error": "Unknown or expired page"}), 404

		with page.lock:
			found = page_components(page)
			if what == "components":
				return jsonify({"components": [{"id": key, "class": label(component)} for key, (component, _) in found.items()]})

			entry = found.get(request.args.get("id"))
			if entry is None:
				return jsonify({"error": "No such component on this page"}), 404

			return jsonify(inspect_component(app, page, entry[0], entry[1], found))

	app.add_url_rule("/_domino/debug.js", "domino_debug_js", script, methods=["GET"])
	app.add_url_rule("/_domino/debug/<what>", "domino_debug", data, methods=["GET"])


# Tracebacks ----------------------------------------------------------------------------------


def is_app_file(path, root):
	"""Whether `path` is the app's own code (or template), not a library's or Domino's."""

	path = os.path.abspath(path)
	if path.startswith(DOMINO_DIR + os.sep) or not path.startswith(root + os.sep):
		return False

	return not any(part in LIBRARY_FOLDERS for part in path[len(root) + 1:].split(os.sep))


def short_path(path, root):

	path = os.path.abspath(path)
	if path.startswith(root + os.sep):
		return path[len(root) + 1:]
	if path.startswith(DOMINO_DIR + os.sep):
		return "domino/" + path[len(DOMINO_DIR) + 1:]
	for folder in ("site-packages", "dist-packages"):
		marker = os.sep + folder + os.sep
		if marker in path:
			return path.split(marker, 1)[1]

	return path


def source_lines(filename, line, around):

	linecache.checkcache(filename)
	lines = linecache.getlines(filename)
	if not lines or line < 1 or line > len(lines):
		return []

	start = max(1, line - around)
	end = min(len(lines), line + around)

	return [[number, lines[number - 1].rstrip("\n")] for number in range(start, end + 1)]


def stack_frames(error, root):
	"""The frames of the error's traceback, outermost first, each with its source around the line
	and whether it's the app's own code."""

	frames = []
	for frame, line in traceback.walk_tb(error.__traceback__):
		filename = frame.f_code.co_filename
		app_frame = is_app_file(filename, root)
		# Average.render rather than render, for methods
		function = frame.f_code.co_name
		owner = frame.f_locals.get("self") if frame.f_code.co_argcount else None
		if owner is not None and not function.startswith("<"):
			function = f"{type(owner).__name__}.{function}"
		frames.append({
			"file": short_path(filename, root),
			"line": line,
			"function": function,
			"app": app_frame,
			"template": filename.endswith((".html", ".jinja", ".j2")),
			"context": source_lines(filename, line, CONTEXT if app_frame else LIBRARY_CONTEXT),
		})

	return frames


def is_component(element):
	"""A component the inspector and the component stack show: the app's own classes, and
	Domino's that render something themselves (forms, accounts), not tags or Document."""

	if not isinstance(element, Element):
		return False
	cls = type(element)
	if cls is Element:
		return False
	if not cls.__module__.startswith("domino"):
		return True

	return cls.__module__ != "domino.tags" and getattr(element, "render", None) is not None


def label(component):

	return type(component).__name__


def component_stack(error):
	"""The components a render error passed through, outermost first (see note_render_error)."""

	noted = error.__dict__.get("domino_components") or [] if hasattr(error, "__dict__") else []

	return [label(component) for component in reversed(noted) if is_component(component)]


def hints(error, frames):
	"""Suggestions for common mistakes, as plain text."""

	from jinja2 import TemplateNotFound, TemplateSyntaxError, UndefinedError

	from .mongo import MongoNotConfigured
	from .templates import TemplateError

	name = type(error).__name__
	message = str(error)
	found = []

	if isinstance(error, MongoNotConfigured):
		found.append(
			"Named Collections (Collection(\"name\")) live in MongoDB. Set mongo.url in settings.json, "
			"e.g. {\"mongo\": {\"url\": \"mongodb://127.0.0.1:27017/myapp?replicaSet=rs0\"}}, or the "
			"DOMINO_MONGO__URL environment variable. `domino run` starts a local MongoDB by itself unless "
			"settings.json has {\"mongo\": {\"auto\": false}}. For data that needn't be shared or kept, "
			"use Collection() without a name (in memory)."
		)
	elif isinstance(error, ValueError) and message.startswith("Invalid child"):
		found.append(
			"A component's render() (or a tag's children) gave something that isn't an element or a "
			"string. Return a tag (t.div() [...]), a component, a string, or a list of them; numbers "
			"need str() or an f-string, and None or False only work inside template strings."
		)
	elif isinstance(error, TemplateNotFound):
		found.append(
			f"Templates are found by file name anywhere in the app's folder (templates/ or next to "
			f"the code that uses them). Check that {message} exists and isn't in a skipped folder "
			"(static/, node_modules/, a hidden folder or a virtualenv)."
		)
	elif isinstance(error, TemplateSyntaxError):
		found.append("The template can't be parsed: check the tag at the line shown (an unclosed {% if %}, a missing }}, ...).")
	elif isinstance(error, UndefinedError):
		found.append(
			"The template uses a name it wasn't given. Pass it to template(name, ...); in a component's "
			"paired template, State values and methods are available by name and the component as `this`."
		)
	elif isinstance(error, TemplateError):
		found.append("Check the template string at the line shown: every tag must be closed, and an interpolation can't be part of a tag or attribute name.")
	elif isinstance(error, KeyError) and any("event.form[" in line for frame in frames[-1:] for _, line in frame["context"]):
		found.append(
			"event.form only has the named fields of the form around the element that fired. Use "
			"event.form.get(\"name\") for fields that may be missing, and give inputs a name=."
		)
	elif isinstance(error, TypeError) and "positional argument" in message and frames and frames[-1]["function"].endswith("handle_event"):
		found.append("An event handler takes no argument or one, the Event: def save(self) or def save(self, event).")
	elif name == "RuntimeError" and "template strings" in message:
		found.append("html(t\"...\") needs Python 3.14. On older versions, write the component with tag classes or a Jinja template.")

	return found


def template_details(error, frames):
	"""For a template that can't be parsed: its file, the line and the source around it."""

	from jinja2 import TemplateSyntaxError

	from .templates import TemplateError

	if isinstance(error, TemplateSyntaxError) and error.lineno:
		filename = error.filename or error.name or "template"
		lines = []
		if error.source:
			source = error.source.splitlines()
			start = max(1, error.lineno - CONTEXT)
			lines = [[number, source[number - 1]] for number in range(start, min(len(source), error.lineno + CONTEXT) + 1)]
		elif error.filename:
			lines = source_lines(error.filename, error.lineno, CONTEXT)
		return {"file": os.path.basename(filename), "line": error.lineno, "context": lines}

	# A t-string's error counts lines from the start of the template, which starts on (or near)
	# the line of the app's frame that called html()
	match = TEMPLATE_LINE.match(str(error)) if isinstance(error, TemplateError) else None
	if match:
		for frame in reversed(frames):
			if frame["app"]:
				return {"file": frame["file"], "line": int(match.group(1)), "relative": True, "context": []}

	return None


def error_details(app, error, callback=None):
	"""What debug.js's error overlay shows beyond the message: the frames with their source, the
	component stack, hints and the template line. Only sent in debug mode."""

	root = os.path.abspath(app.root_path)
	frames = stack_frames(error, root)
	details = {
		"frames": frames,
		"components": component_stack(error),
		"hints": hints(error, frames),
	}

	template = template_details(error, frames)
	if template:
		details["template"] = template
	if callback is not None:
		details["handler"] = describe_callback(callback)

	return details


# The error page ------------------------------------------------------------------------------


PAGE_CSS = """
:root { color-scheme: light dark; --bg: #f6f6f4; --card: #fff; --text: #1d1d1f; --muted: #6b6b70;
	--line: #e3e3e0; --accent: #c4302b; --hl: #fff4d6; --app: #1f6feb; --code: #fafaf8; }
@media (prefers-color-scheme: dark) { :root { --bg: #141416; --card: #1d1d20; --text: #ececec;
	--muted: #9a9aa2; --line: #2e2e33; --accent: #ff6b63; --hl: #3b3317; --app: #6ea8fe; --code: #18181b; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 980px; margin: 0 auto; padding: 2rem 1rem 4rem; }
header { border-left: 6px solid var(--accent); padding: .25rem 0 .25rem 1.25rem; margin-bottom: 2rem; }
.kind { margin: 0; color: var(--accent); font-weight: 700; letter-spacing: .02em; }
h1 { margin: .25rem 0 .5rem; font-size: 1.9rem; line-height: 1.25; overflow-wrap: anywhere; white-space: pre-wrap; }
.where { margin: 0; color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .9rem; }
h2 { font-size: .8rem; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); margin: 2rem 0 .75rem; }
section { margin-bottom: 1rem; }
.hint { background: var(--card); border: 1px solid var(--line); border-left: 4px solid #d29922; border-radius: 6px; padding: .75rem 1rem; margin: 0 0 .5rem; }
.path { display: flex; flex-wrap: wrap; gap: .25rem; list-style: none; padding: 0; margin: 0; font-family: ui-monospace, monospace; }
.path li { background: var(--card); border: 1px solid var(--line); border-radius: 4px; padding: .1rem .5rem; }
.path li { position: relative; }
.path li + li { margin-left: 1rem; }
.path li + li::before { content: "›"; color: var(--muted); position: absolute; left: -.85rem; font-weight: 400; }
.path li.failed { border-color: var(--accent); color: var(--accent); font-weight: 600; }
.frame { background: var(--card); border: 1px solid var(--line); border-radius: 6px; margin: 0 0 .5rem; overflow: hidden; }
.frame.app { border-left: 4px solid var(--app); }
.frame-head { display: flex; justify-content: space-between; gap: 1rem; padding: .45rem .75rem; font-family: ui-monospace, monospace; font-size: .85rem; }
.frame-head .function { font-weight: 600; }
.frame-head .file { color: var(--muted); overflow-wrap: anywhere; text-align: right; }
.badge { font-size: .7rem; border: 1px solid currentColor; border-radius: 3px; padding: 0 .3rem; margin-left: .4rem; color: var(--app); }
.source { margin: 0; background: var(--code); border-top: 1px solid var(--line); font: 13px/1.55 ui-monospace, SFMono-Regular, Menlo, monospace; overflow-x: auto; padding: .35rem 0; }
.source div { white-space: pre; padding: 0 .75rem; }
.source .current { background: var(--hl); }
.source .number { display: inline-block; width: 3.5em; color: var(--muted); user-select: none; }
details.library { margin: 0 0 .5rem; }
details.library > summary { cursor: pointer; color: var(--muted); font-size: .9rem; padding: .3rem .25rem; }
details.library .frame { opacity: .85; }
table { width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--line); border-radius: 6px; font-size: .9rem; }
th, td { text-align: left; vertical-align: top; padding: .35rem .75rem; border-top: 1px solid var(--line); overflow-wrap: anywhere; }
th { width: 12rem; color: var(--muted); font-weight: 500; }
tr:first-child th, tr:first-child td { border-top: 0; }
pre.plain { background: var(--card); border: 1px solid var(--line); border-radius: 6px; padding: .75rem; font: 12px/1.5 ui-monospace, monospace; overflow-x: auto; }
footer { margin-top: 2.5rem; color: var(--muted); font-size: .85rem; }
"""


def render_frame(frame):

	classes = "frame app" if frame["app"] else "frame"
	badge = '<span class="badge">template</span>' if frame["template"] else ""
	head = (
		f'<div class="frame-head"><span class="function">{escape(frame["function"])}{badge}</span>'
		f'<span class="file">{escape(frame["file"])}:{frame["line"]}</span></div>'
	)
	lines = "".join(
		f'<div class="{"current" if number == frame["line"] else "line"}"><span class="number">{number}</span>{escape(text)}</div>'
		for number, text in frame["context"]
	)
	source = f'<div class="source">{lines}</div>' if lines else ""

	return f'<div class="{classes}" data-app="{"true" if frame["app"] else "false"}">{head}{source}</div>'


def render_frames(frames):
	"""The app's frames open, each run of library frames folded into one <details>."""

	html = []
	run = []

	def flush():
		if not run:
			return
		where = sorted({frame["file"].split("/")[0] for frame in run})
		summary = f'{len(run)} library frame{"s" if len(run) > 1 else ""} ({escape(", ".join(where[:3]))}{", ..." if len(where) > 3 else ""})'
		html.append(f'<details class="library"><summary>{summary}</summary>{"".join(render_frame(frame) for frame in run)}</details>')
		run.clear()

	for frame in frames:
		if frame["app"]:
			flush()
			html.append(render_frame(frame))
		else:
			run.append(frame)
	flush()

	return "".join(html)


def table(rows):

	return "<table>" + "".join(f"<tr><th>{escape(name)}</th><td>{escape(value)}</td></tr>" for name, value in rows) + "</table>"


def error_page(app, error):
	"""The page shown in debug mode for an exception while handling a request (usually a page
	whose render failed). Everything from the exception or the request is escaped."""

	details = error_details(app, error)
	frames = details["frames"]
	app_frames = [frame for frame in frames if frame["app"]]
	last = app_frames[-1] if app_frames else (frames[-1] if frames else None)

	kind = type(error).__name__
	message = str(error) or kind
	where = f'in {last["function"]}() · {last["file"]}:{last["line"]}' if last else ""
	if details["components"] and not app_frames:
		where = f'while rendering {details["components"][-1]}'

	parts = [
		f'<header><p class="kind">{escape(kind)}</p><h1>{escape(message)}</h1><p class="where">{escape(where)}</p></header>'
	]

	if details["hints"]:
		parts.append('<section class="hints"><h2>Hint</h2>' + "".join(f'<p class="hint">{escape(hint)}</p>' for hint in details["hints"]) + "</section>")

	components = details["components"]
	if components:
		items = "".join(
			f'<li{" class=failed" if index == len(components) - 1 else ""}>{escape(name)}</li>'
			for index, name in enumerate(components)
		)
		parts.append(f'<section class="components"><h2>Component stack</h2><ol class="path">{items}</ol></section>')

	template = details.get("template")
	if template:
		where = f'{template["file"]}, line {template["line"]}'
		if template.get("relative"):
			where = f'line {template["line"]} of the template string in {template["file"]}'
		lines = "".join(
			f'<div class="{"current" if number == template["line"] else "line"}"><span class="number">{number}</span>{escape(text)}</div>'
			for number, text in template["context"]
		)
		source = f'<div class="source">{lines}</div>' if lines else ""
		parts.append(
			f'<section class="template"><h2>Template</h2><div class="frame app">'
			f'<div class="frame-head"><span class="function">{escape(where)}</span></div>{source}</div></section>'
		)

	cause = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
	if cause is not None:
		parts.append(f'<section class="cause"><h2>Caused by</h2><p class="hint">{escape(type(cause).__name__)}: {escape(str(cause))}</p></section>')

	parts.append(f'<section class="traceback"><h2>Traceback <small>(most recent call last)</small></h2>{render_frames(frames)}</section>')

	rows = [("Method", request.method), ("URL", request.url), ("Endpoint", request.endpoint or "")]
	if request.view_args:
		rows.append(("URL parameters", ", ".join(f"{name}={value!r}" for name, value in request.view_args.items())))
	for name in ("Referer", "User-Agent", "Accept-Language"):
		if request.headers.get(name):
			rows.append((name, request.headers[name]))
	rows.append(("Python", sys.version.split()[0]))
	parts.append(f'<section class="request"><h2>Request</h2>{table(rows)}</section>')

	plain = "".join(traceback.format_exception(type(error), error, error.__traceback__))
	parts.append(f'<section><details><summary>Plain traceback</summary><pre class="plain">{escape(plain)}</pre></details></section>')

	parts.append("<footer>Shown because the app runs in debug mode. Without it, visitors get a plain 500 Internal Server Error with no details.</footer>")

	return (
		"<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
		"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
		f"<title>{escape(kind)}: {escape(message[:120])} · Domino</title><style>{PAGE_CSS}</style></head>"
		f"<body><main class=\"domino-error-page\">{''.join(parts)}</main></body></html>\n"
	)


# The inspector -------------------------------------------------------------------------------


def element_key(element):
	"""The id a component has in the page, without marking it used (see Element.id)."""

	explicit = element.__attributes__.get("id")
	if explicit:
		return str(explicit)

	return str(element.__id__) if element.__id__ is not None else None


def page_components(page):
	"""{id: (component, [ancestor components, outermost first])} for the components `page` shows,
	found from its root, the elements its events are bound to and its live components."""

	found = {}
	seen = set()
	roots = [getattr(page, "root", None)]
	for element, callback in page.events.values():
		roots.append(element)
		roots.append(getattr(callback, "__self__", None))
	roots.extend(page.components)

	for root in roots:
		if not isinstance(root, Element) or id(root) in seen:
			continue
		stack = [(root, [])]
		while stack:
			element, ancestors = stack.pop()
			if id(element) in seen:
				continue
			seen.add(id(element))
			if is_component(element):
				key = element_key(element)
				if key is not None:
					found.setdefault(key, (element, ancestors))
				ancestors = ancestors + [element]
			children = list(element.__children__) + list(getattr(element, "__embedded__", ()))
			for child in reversed(children):
				if isinstance(child, Element):
					stack.append((child, ancestors))

	return found


def short_repr(value):

	if isinstance(value, Element):
		return f"<{type(value).__name__}>"

	try:
		text = repr(value)
	except Exception as error:
		text = f"<repr failed: {type(error).__name__}>"

	if len(text) > MAX_REPR:
		text = text[:MAX_REPR - 1] + "…"

	return text


def describe_callback(callback):
	"""A handler's name for people: "TodoList.add", "lambda (todo_list.py:21)", "save"."""

	function = getattr(callback, "__func__", callback)
	owner = getattr(callback, "__self__", None)
	name = getattr(function, "__name__", None) or type(callback).__name__

	if name == "<lambda>":
		code = function.__code__
		return f"lambda ({os.path.basename(code.co_filename)}:{code.co_firstlineno})"
	if owner is not None and not isinstance(owner, types.ModuleType):
		return f"{type(owner).__name__}.{name}"

	return getattr(function, "__qualname__", name)


def describe_element(element):

	if not isinstance(element, Element):
		return "(none)"

	text = ""
	for child in element.__children__:
		if isinstance(child, str) and child.strip():
			text = child.strip()
			break
	if len(text) > 30:
		text = text[:29] + "…"

	tag = element.__tag__ or type(element).__name__
	name = element.__attributes__.get("name")
	description = f"<{tag}{f' name={name}' if name else ''}>"
	if is_component(element):
		description = f"{type(element).__name__} {description}"

	return f"{description} {text}".strip()


def source_location(cls):

	try:
		path = inspect.getsourcefile(cls)
		line = inspect.getsourcelines(cls)[1]
	except (OSError, TypeError):
		return None, None

	return path, line


def subscriptions(app, page, component):
	"""What the component's last render read: its own State, shared State, Collections."""

	wanted = {id(dependency) for dependency in component.__dependencies__}
	if not wanted:
		return []

	found = []
	cls = type(component)
	for name in sorted(optimistic.state_names(cls)):
		state = component.__dict__.get(f"__state_{name}__")
		if state is not None and id(state._dependency) in wanted:
			wanted.discard(id(state._dependency))
			found.append(f"self.{name} (State)")

	if not wanted:
		return found

	# Shared State and Collections, found among the objects in memory: slow, but on demand
	names = global_names(app)
	for value in gc.get_objects():
		if not isinstance(value, (State, Collection)) or id(value._dependency) not in wanted:
			continue
		wanted.discard(id(value._dependency))
		where = names.get(id(value))
		if value is page.user_id:
			found.append("the signed-in user (accounts)")
		elif isinstance(value, Collection):
			kind = f'Collection("{value.name}")' if value.name else "Collection() (in memory)"
			found.append(f"{where}: {kind}" if where else kind)
		else:
			found.append(f"{where} (State)" if where else short_repr(value))

	found.extend("(something else reactive)" for _ in wanted)

	return found


def global_names(app):
	"""id(value) -> "module.name" for module-level values of the app's own modules."""

	root = os.path.abspath(app.root_path)
	names = {}
	for module in list(sys.modules.values()):
		path = getattr(module, "__file__", None)
		if not path or not is_app_file(path, root):
			continue
		short = os.path.splitext(short_path(path, root))[0].replace(os.sep, ".")
		for name, value in list(vars(module).items()):
			if isinstance(value, (State, Collection)):
				names.setdefault(id(value), f"{short}.{name}")

	return names


def inspect_component(app, page, component, ancestors, found):
	"""The inspector's panel for one component, as JSON-ready data."""

	cls = type(component)
	root = os.path.abspath(app.root_path)
	path, line = source_location(cls)

	state = []
	for name in sorted(optimistic.state_names(cls)):
		value = getattr(cls, name)._of(component)._value
		state.append({"name": name, "value": short_repr(value)})

	attributes = [
		{"name": name, "value": short_repr(value)}
		for name, value in component.__attributes__.items()
		if name not in ("data_event_id", "data_after_id", "data_domino_page", "id")
	]

	fields = [
		{"name": name, "value": short_repr(value)}
		for name, value in vars(component).items()
		if not name.startswith("_") and name not in ("content_root", "init")
	]

	bound = getattr(component, "__bound__", None)
	if bound is None:
		bound = [(event_id, callback) for event_id, (element, callback) in page.events.items() if element is component]

	events = []
	for event_id, callback in bound:
		event = page.events.get(event_id)
		if event is None:
			continue
		reason = optimistic.explain(component, callback, event[0])
		events.append({
			"id": event_id,
			"event": event_id.rsplit("-", 1)[-1],
			"element": describe_element(event[0]),
			"handler": describe_callback(callback),
			"predicted": reason is None,
			"reason": reason,
		})

	children = [
		{"id": key, "class": label(other)}
		for key, (other, chain) in found.items()
		if chain and chain[-1] is component
	]

	return {
		"id": element_key(component),
		"class": cls.__name__,
		"module": cls.__module__,
		"file": short_path(path, root) if path else None,
		"line": line,
		"tag": component.__tag__,
		"live": component.is_live(),
		"state": state,
		"attributes": attributes,
		"fields": fields,
		"events": events,
		"subscriptions": subscriptions(app, page, component),
		"ancestors": [{"id": element_key(other), "class": label(other)} for other in ancestors],
		"children": children,
	}


# Startup -------------------------------------------------------------------------------------


def startup_warnings(app):
	"""Short warnings about things that work while developing but not in production, logged
	once when a debug server starts."""

	if getattr(app, "_domino_warned", False):
		return
	app._domino_warned = True

	from . import devmongo, mongo

	root = os.path.abspath(app.root_path)
	no_mongo = not callable(mongo._url) and not mongo.configured_url() and devmongo.disabled_reason(app.settings)
	seen = set()
	for module in list(sys.modules.values()):
		path = getattr(module, "__file__", None)
		if not path or not is_app_file(path, root):
			continue
		where = short_path(path, root)
		for name, value in list(vars(module).items()):
			if id(value) in seen or not isinstance(value, Collection):
				continue
			seen.add(id(value))
			if value.name is None:
				app.logger.warning(
					"Domino: %s: %s = Collection() is kept in this process's memory: it's emptied on restart, "
					"and with `domino serve --workers N` each worker has its own. Collection(%r) stores it in MongoDB.",
					where, name, name
				)
			elif no_mongo:
				app.logger.warning(
					"Domino: %s: %s = Collection(%r) needs MongoDB, but mongo.url isn't set and the development "
					"MongoDB is turned off (\"mongo\": {\"auto\": false}, --no-mongo or DOMINO_NO_MONGO).",
					where, name, value.name
				)
