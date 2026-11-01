"""Hot reloading while debugging, like React Fast Refresh: saving a file updates the open pages in
place, keeping their components' State, instead of restarting the server.

`domino run` and `app.run(debug=True)` serve the app in a process of its own (see serve()), where
a thread watches the app's folder (with watchfiles, or by polling without it) and hands each batch
of changed files to HotReloader.reload(), which:

- runs the app's modules that changed again, from their source, in place, and then the modules of
  the app that import them, dependencies first. Only modules already imported from the app's
  folder count; reactive data at their top level (State, Collection) is kept;
- points the components on open pages at the new classes (obj.__class__ = New), keeping their
  State: new State attributes start at their defaults, removed ones are dropped;
- forgets what Domino keeps per class (predictions, CSS, paired templates, class attributes), and
  gives the routes of pages/ their new views (or adds and removes pages);
- updates every open page over its socket (or stream): the components whose class changed are
  rendered again, or the whole page when its page or layout module changed (its view runs again,
  and the components it makes take over the State and ids of those in the same places, as when a
  parent renders again) or a Jinja template did. The browser morphs the page, so focus and what's
  typed stay. Stylesheets are fetched again, and other static files reload the page.

What can't be swapped in safely restarts the server process instead, and the open tabs reload: the
app's own module (app.py) and anything that imports it, settings files, deleted modules, and
modules that start threads, processes or apps, or add routes, at import (a guess from their code,
see restart_only(): running them twice would do it twice). A module can decide for itself with
`__hot_reload__ = False` (always restart) or `__hot_reload__ = True` (always reload). Changes
outside the app's folder (Domino, installed packages) aren't watched.

An error while reloading (a syntax error, say) leaves the old code running and shows the error in
the open tabs until a save fixes it.
"""

import ast
import linecache
import os
import sys
import threading
import time
import tokenize
import traceback
from contextlib import nullcontext
from pathlib import Path

from flask import g, request
import uvicorn
from uvicorn._subprocess import get_subprocess
from uvicorn.supervisors.basereload import BaseReload

from . import core, optimistic, util
from .core import Element, collect_styles
from .util import css_class_name
from .optimistic import state_names
from .reactive import Collection, State


# The exit code of a server process that needs replacing (see Supervisor)
RESTART_EXIT = 3

# Seconds between the supervisor's looks at its server process
CHECK_INTERVAL = 0.1

# Milliseconds without another change before a batch of changes is handled
WATCH_STEP = 50

# Seconds between scans when watchfiles isn't installed
POLL_INTERVAL = 0.25

# Files that matter; others in the app's folder (data, logs, uploads) change without a reload
WATCHED = (".py", ".html", ".css", ".js", ".json")

# Folders never watched, as for templates (see domino.templates), and hidden ones
SKIPPED = ("__pycache__", "node_modules", "site-packages")

# Calls at a module's top level (by name) that would do something twice if the module ran twice:
# threads, processes and apps started, routes and handlers added
RESTART_CALLS = {
	"Thread", "Timer", "Process", "Pool", "ThreadPoolExecutor", "ProcessPoolExecutor", "Popen",
	"start_new_thread", "start", "Domino", "Flask", "Blueprint", "route", "add_url_rule",
	"register_blueprint", "register_error_handler", "errorhandler", "before_request",
	"after_request", "teardown_request", "register", "signal",
}


class Visit:
	"""What made a page: its view with the URL's parameters, the request's URL and cookies, and
	the element the view returned, to render again, or make again, when files change."""


	def __init__(self, root, view, args, kwargs):

		self.root = root
		self.view = view
		self.args = args
		self.kwargs = kwargs
		self.path = request.full_path
		self.base_url = request.root_url
		self.cookie = request.headers.get("Cookie")


class HotReloader:
	"""Swaps changed files into a running app and updates its open pages (see the module's doc).
	`app_file` is the app's own module, which can't be reloaded (default: found from the app)."""


	def __init__(self, app, app_file=None):

		self.app = app
		self.root = Path(os.path.realpath(app.root_path))
		self.app_file = None
		if app_file is None:
			from .asgi import app_location
			location = app_location(app) or ""
			# "path/to/app.py:app" (C:\path\to\app.py:app on Windows), or a folder
			if location.rpartition(":")[0].endswith(".py"):
				app_file = location.rpartition(":")[0]
		if app_file:
			self.app_file = Path(os.path.realpath(app_file))
		self.lock = threading.Lock()
		self.stop = threading.Event()
		self.thread = None
		self.error = False  # the last reload failed, and the open tabs show why
		self.errors = set()  # pages that failed to render after the last reload, and show why
		self.imports = {}  # file -> ((mtime, size), names it imports), so files are parsed once

		app.hot_reloader = self


	def start(self):
		"""Watch the app's folder in a thread of its own."""

		self.thread = threading.Thread(target=self.watch, name="domino-hot-reload", daemon=True)
		self.thread.start()

		return self


	def watch(self):

		for paths in watch(self.root, self.stop, self.watched):
			self.reload(paths)


	def watched(self, path):

		return watched(self.root, path)


	def remember(self, page, root, view, args, kwargs):
		"""Called while a view's page is rendered (see Domino._render_view)."""

		page.hot = Visit(root, view, args, kwargs)


	def restart(self, reason):
		"""Exit, for the supervisor to start a new process; the open tabs reload once it's up."""

		log(f"restarting: {reason}")
		os._exit(RESTART_EXIT)


	def reload(self, paths):
		"""Handle a batch of changed files. Returns "hot", "restart", "error", or None when none
		of them mattered."""

		started = time.perf_counter()

		with self.lock:
			try:
				return self.swap(paths, started)
			except Exception as error:
				# A mistake of Domino's: say so and keep serving
				log(f"hot reload failed: {type(error).__name__}: {error}\n{traceback.format_exc()}")
				return "error"


	def swap(self, paths, started):

		paths = sorted({Path(os.path.realpath(path)) for path in paths if self.watched(path)})
		if not paths:
			return None
		names = ", ".join(self.relative(path) for path in paths)

		modules = self.app_modules()
		folder = getattr(self.app, "_pages_folder", None)
		changed = []
		pages_changed = False  # pages or layouts added or deleted
		templates, stylesheets, assets = set(), False, False

		for path in paths:
			if path == self.app_file or self.is_settings(path):
				self.restart(f"{self.relative(path)} changed")
				return "restart"
			page = folder is not None and is_page_file(folder, path)
			if path.suffix == ".py" and not path.exists():
				if page:
					pages_changed = True
				elif path in modules:
					self.restart(f"{self.relative(path)} was deleted")
					return "restart"
			elif path.suffix == ".py":
				# A module nothing imports yet is picked up when something does
				changed.extend(modules.get(path, ()))
				pages_changed = pages_changed or (page and path not in modules)
			elif path.suffix == ".html":
				templates.add(str(path))
				# A template in pages/ may be a page (see domino.pages): its route may come or go
				pages_changed = pages_changed or (folder is not None and is_page_file(folder, path.with_suffix(".py")))
			elif path.suffix == ".css":
				stylesheets = True
			elif path.suffix == ".js":
				assets = True

		order = self.reload_order(changed, modules)
		for module in order:
			path = Path(os.path.realpath(module.__file__))
			if path == self.app_file or restart_only(path):
				self.restart(f"{names} changed" + (f" ({self.relative(path)} can't be hot reloaded)" if path not in paths else ""))
				return "restart"

		if not (order or pages_changed or templates or stylesheets or assets):
			return None

		try:
			done = self.execute(order)
		except Exception as error:
			self.failed(error, names)
			return "error"

		# Page views hold the functions of their modules, so they're made again
		if folder is not None and (pages_changed or any(folder in Path(os.path.realpath(module.__file__)).parents for module in order)):
			try:
				self.add_pages(folder)
			except Exception as error:
				rollback(done)
				self.failed(error, names)
				return "error"

		classes = new_classes(done)
		css_changed = any(issubclass(new, Element) and component_text(old) != component_text(new) for old, new in classes.items())
		forget_caches(self.app, templates)

		try:
			self.swap_classes(classes)
		except TypeError as error:
			self.restart(f"{names} changed ({error})")
			return "restart"

		count = self.update_pages({module.__name__ for module in changed}, set(classes.values()), pages_changed, templates, css_changed, stylesheets, assets)
		self.error = False

		log(f"hot reloaded {names} ({count} page{'' if count == 1 else 's'}) in {(time.perf_counter() - started) * 1000:.0f} ms")

		return "hot"


	def relative(self, path):

		try:
			return Path(path).relative_to(self.root).as_posix()
		except ValueError:
			return str(path)


	def is_settings(self, path):

		if path.suffix != ".json":
			return False

		# settings.json, settings.local.json or another file the app reads (see domino.settings)
		other = os.environ.get("DOMINO_SETTINGS")
		if other:
			other = Path(os.path.realpath(other))
			if path in (other, other.with_suffix(".local" + other.suffix)):
				return True

		return path.parent == self.root


	def app_modules(self):
		"""{file: [modules]} of the modules imported from the app's folder."""

		roots = (str(self.root) + os.sep, os.path.abspath(self.app.root_path) + os.sep)
		found = {}
		for name, module in list(sys.modules.items()):
			path = getattr(module, "__file__", None)
			if not path or name.split(".")[0] == "domino" or not os.path.abspath(path).startswith(roots):
				continue
			path = Path(os.path.realpath(path))
			if path.suffix == ".py" and self.watched(path):
				found.setdefault(path, []).append(module)

		return found


	def reload_order(self, changed, modules):
		"""The changed modules and every app module that imports one (directly or not), each
		after the modules it imports."""

		by_name = {module.__name__: module for found in modules.values() for module in found}
		imports = {name: self.imported(module) & by_name.keys() for name, module in by_name.items()}

		importers = {}
		for name, imported in imports.items():
			for other in imported:
				importers.setdefault(other, set()).add(name)

		selected = {module.__name__ for module in changed}
		pending = list(selected)
		while pending:
			for name in importers.get(pending.pop(), ()):
				if name not in selected:
					selected.add(name)
					pending.append(name)

		order = []
		visiting = set()

		def visit(name):
			if name in visiting or by_name[name] in order:
				return
			visiting.add(name)
			for other in sorted(imports[name] & selected):
				visit(other)
			order.append(by_name[name])

		for name in sorted(selected):
			visit(name)

		return order


	def imported(self, module):
		"""Names of the modules `module` imports (and of their packages), from its source."""

		path = module.__file__
		try:
			stat = os.stat(path)
		except OSError:
			return set()
		key = (stat.st_mtime_ns, stat.st_size)

		cached = self.imports.get(path)
		if cached is None or cached[0] != key or cached[2] != module.__name__:
			try:
				names = imported_names(ast.parse(read_source(path)), module.__package__ or "")
			except (OSError, SyntaxError, ValueError):
				names = set()
			cached = self.imports[path] = (key, names, module.__name__)

		return cached[1]


	def execute(self, order):
		"""Run each module again in place, all or none: if one fails, every one goes back to how
		it was. Returns [(module, its namespace before)]."""

		done = []
		try:
			for module in order:
				before = dict(module.__dict__)
				done.append((module, before))
				# Compiled from the source, not from a .pyc that a quick second save could match
				exec(compile(read_source(module.__file__), module.__file__, "exec"), module.__dict__)
				keep_reactive(module, before)
		except Exception:
			rollback(done)
			raise

		return done


	def add_pages(self, folder):

		from .pages import add_pages

		# Flask allows no new routes once it has served a request, for good reason; the routes
		# of pages are only added to, and the app isn't serving anything else meanwhile
		served = self.app._got_first_request
		self.app._got_first_request = False
		try:
			add_pages(self.app, folder, reload=True)
		finally:
			self.app._got_first_request = served


	def pages(self):
		"""The open pages (pages kept somewhere other than this process's memory aren't updated)."""

		store = self.app.page_store
		pages = getattr(store, "pages", None)
		if pages is None:
			return []

		with getattr(store, "lock", None) or nullcontext():
			return list(pages.values())


	def swap_classes(self, classes):
		"""Point the elements on open pages whose class was reloaded at the new class."""

		if not classes:
			return

		for page in self.pages():
			roots = [element for element, _ in page.events.values()] + list(page.components)
			if page.hot is not None:
				roots.append(page.hot.root)
			for element in walk(roots):
				new = classes.get(type(element))
				if new is None:
					continue
				element.__class__ = new
				# State the class doesn't have any more goes; new State starts at its default
				names = state_names(new)
				for key in [key for key in element.__dict__ if key.startswith("__state_") and key.endswith("__")]:
					if key[len("__state_"):-2] not in names:
						del element.__dict__[key]


	def update_pages(self, edited, classes, pages_changed, templates, css_changed, stylesheets, assets):
		"""Send each open page what changed. Returns how many pages were updated."""

		from .pages import PageRoute
		from .templates import paired_template

		paired = {}

		def own_template(cls):
			if cls not in paired:
				paired[cls] = paired_template(cls)
			return paired[cls]

		def renders(element):
			return getattr(element, "render", None) is not None or own_template(type(element)) is not None

		def wanted(element):
			return type(element) in classes or own_template(type(element)) in templates

		visits = [(page, page.hot) for page in self.pages() if page.hot is not None]

		# Pages that showed an error while rendering last time
		shown_errors = self.errors
		self.errors = set()

		# Templates that aren't a live component's own are part of some page
		shown = {own_template(type(element)) for _, visit in visits for element in walk([visit.root])}
		whole = bool(templates - shown)

		updated = set()
		refresh = {}  # component -> the visit to render it in
		messages = []
		for page, visit in visits:
			# A script changed, or the page's file was deleted: load it again
			if assets or (isinstance(visit.view, PageRoute) and visit.view.view is None):
				page.notify({"type": "hot", "reload": True})
				updated.add(page)
				continue

			# The view runs again when its page or a layout was edited; one only reloaded for
			# importing a changed module made the same elements, now pointed at the new classes
			view_modules = getattr(visit.view, "modules", None) or {getattr(visit.view, "__module__", None)}
			rerun = (pages_changed and isinstance(visit.view, PageRoute)) or bool(set(view_modules) & edited)
			parts = None
			if not (rerun or whole):
				parts = changed_parts(visit.root, wanted, renders)
			if rerun or whole or parts is None:
				self.render_page(page, visit, rerun)
				updated.add(page)
				continue

			for part in parts:
				refresh.setdefault(part, visit)
			message = {"type": "hot"}
			if css_changed:
				message["css"] = None  # filled in once the components are rendered
			if stylesheets:
				message["stylesheets"] = True
			if self.error or page in shown_errors:
				message["error"] = None  # what went wrong before is put right
			if parts or len(message) > 1:
				messages.append((page, visit, message))
				updated.add(page)

		for component, visit in refresh.items():
			try:
				with self.request_context(visit):
					component.refresh()
			except Exception as error:
				for page in list(component.__pages__ or ()):
					self.show_error(page, error)

		for page, visit, message in messages:
			if "css" in message:
				message["css"] = page_css(visit.root)
			if page in self.errors:
				message.pop("error", None)
			page.notify(message)

		return len(updated)


	def request_context(self, visit):

		headers = {"Cookie": visit.cookie} if visit.cookie else {}

		return self.app.test_request_context(visit.path, base_url=visit.base_url, headers=headers)


	def render_page(self, page, visit, rerun):
		"""Render a whole page again and send it, or with `rerun`, make it again with its view, the
		new components taking over the State of the old ones in their places."""

		try:
			with self.request_context(visit), page.lock:
				g.domino_page = page
				root = visit.root
				events = dict(page.events)
				replaced = []
				if rerun:
					# Its events are all bound again, by the view and by rendering
					page.events.clear()
				try:
					if rerun:
						root = visit.view(*visit.args, **visit.kwargs)
						if not isinstance(root, Element):
							page.notify({"type": "hot", "reload": True})
							return
						replaced = adopt(visit.root, root)
						for key, value in visit.root.__attributes__.items():
							if key.startswith("data_domino"):
								root.configure(**{key: value})
					with collect_styles() as styles:
						html = root._render()
				except Exception:
					page.events.clear()
					page.events.update(events)
					raise
				for old, new in replaced:
					core.retire(old, new)
				html = styles.finish(html)
				page.css = set(styles.classes)
				visit.root = root
		except Exception as error:
			self.show_error(page, error)
			return

		page.notify({"type": "hot", "html": html, "error": None})


	def show_error(self, page, error):

		text = describe(error)
		log(f"hot reload: rendering the page failed:\n{text.rstrip()}")
		self.errors.add(page)
		page.notify({"type": "hot", "error": f"{type(error).__name__}: {error}", "traceback": text})


	def failed(self, error, names):
		"""Show why a reload failed in every open tab; the old code keeps running."""

		text = describe(error)
		log(f"hot reload of {names} failed, still running the code from before:\n{text.rstrip()}")
		self.error = True

		for page in self.pages():
			if page.hot is not None:
				page.notify({"type": "hot", "error": f"{type(error).__name__}: {error}", "traceback": text})


def log(message):

	print(f"domino: {message}", file=sys.stderr, flush=True)


def describe(error):
	"""The traceback of an error in the app's code, without the frames of this module."""

	frames = [frame for frame in traceback.extract_tb(error.__traceback__) if frame.filename != __file__]
	text = "".join(traceback.format_exception_only(type(error), error))
	if frames:
		text = "Traceback (most recent call last):\n" + "".join(traceback.format_list(frames)) + text

	return text


def read_source(path):

	# Honours an encoding declaration, as imports do
	with tokenize.open(path) as file:
		return file.read()


def rollback(done):

	for module, before in reversed(done):
		module.__dict__.clear()
		module.__dict__.update(before)


def keep_reactive(module, before):
	"""Keep the module's State and Collection objects from before: components subscribe to them,
	and they hold data (an in-memory Collection's documents, a named one's change stream)."""

	namespace = module.__dict__
	for name, old in before.items():
		new = namespace.get(name)
		if new is old:
			continue
		if isinstance(old, State) and type(new) is type(old):
			namespace[name] = old
		elif isinstance(old, Collection) and type(new) is type(old) and new.name == old.name:
			namespace[name] = old


def new_classes(done):
	"""{old class: new class} for the classes the reloaded modules define again."""

	classes = {}
	for module, before in done:
		for name, old in before.items():
			new = module.__dict__.get(name)
			if (
				isinstance(old, type) and isinstance(new, type) and new is not old
				and old.__module__ == new.__module__ == module.__name__ and old.__qualname__ == new.__qualname__
			):
				classes[old] = new

	return classes


def component_text(cls):

	# What the class's own `css` renders to (see core.component_css), without the cache
	return core.css.render(cls.__dict__.get("css") or {}, f".{css_class_name(cls)}")


def forget_caches(app, templates):
	"""Forget what Domino worked out per class or per file, which the new code may change."""

	optimistic._methods.clear()
	optimistic._callable.clear()
	optimistic._lambdas.clear()
	optimistic._sources.clear()
	optimistic._state_lists.clear()
	util._class_attributes.clear()
	core._component_css.clear()
	core._paired_templates.clear()
	core._component_props.clear()

	# Domino templates are parsed again, and the files defining components found again
	from . import dtemplates
	dtemplates.forget()
	dtemplates._class_names.clear()
	finder = getattr(app, "template_finder", None)
	if finder is not None and templates:
		finder.stale = True

	# inspect.getsource() (predictions read handlers' code) goes through linecache
	linecache.clearcache()

	if templates and app.jinja_env.cache is not None:
		app.jinja_env.cache.clear()


def walk(roots):
	"""The elements in these trees (including the children components' render() made)."""

	seen = set()
	stack = list(roots)
	while stack:
		element = stack.pop()
		if not isinstance(element, Element) or id(element) in seen:
			continue
		seen.add(id(element))
		yield element
		stack.extend(element.__children__)
		stack.extend(getattr(element, "__embedded__", ()))


def changed_parts(root, wanted, renders):
	"""The outermost components under `root` to render again: those `wanted`, or the nearest one
	around a wanted element that doesn't render itself. None when that's the whole page."""

	found = []
	seen = set()

	def visit(element, owner):
		if not isinstance(element, Element) or id(element) in seen:
			return True
		seen.add(id(element))
		own = renders(element)
		if wanted(element):
			target = element if own else owner
			if target is None:
				return False
			if all(part is not target for part in found):
				found.append(target)
			return True
		owner = element if own else owner
		for child in list(element.__children__) + list(getattr(element, "__embedded__", ())):
			if not visit(child, owner):
				return False
		return True

	if not visit(root, None):
		return None

	return found


def made_by_view(root):
	"""The elements of a page its view made, in order: not those components' render() made."""

	stack = [root]
	while stack:
		element = stack.pop()
		if not isinstance(element, Element):
			continue
		yield element
		if getattr(element, "render", None) is None:
			stack.extend(reversed(element.__children__))


def adopt(old, new):
	"""Give the elements a page's view made again (`new`) the State and ids of those it made
	before (`old`) in the same places: the first Counter takes over the first Counter's, and so
	on. The components their render() makes are matched in turn as they render, as whenever
	they're rendered (see core.Matches). Gives the (old, new) pairs."""

	def key(element):
		cls = type(element)
		return (cls.__module__, cls.__qualname__, element.__tag__)

	previous = {}
	for element in made_by_view(old):
		previous.setdefault(key(element), []).append(element)

	counts = {}
	replaced = []
	for element in made_by_view(new):
		index = counts.get(key(element), 0)
		counts[key(element)] = index + 1
		olds = previous.get(key(element), [])
		if index >= len(olds):
			continue
		# The same State and id, so the browser keeps the same node (and its focus, and what's
		# typed in it)
		core.take_over(olds[index], element)
		replaced.append((olds[index], element))

	return replaced


def page_css(root):
	"""[name, css] of every component class with `css` on the page (see core.PageStyles)."""

	found = {}
	for element in walk([root]):
		for base in reversed(type(element).__mro__):
			if base in (object, Element) or base.__module__ == "domino.tags" or base.__name__ == element.__tag__:
				continue
			if "css" in base.__dict__ and css_class_name(base) not in found:
				text = core.component_css(base)
				if text:
					found[css_class_name(base)] = text

	return [[name, text] for name, text in found.items()]


def imported_names(tree, package):
	"""Names of the modules a module's code imports, and of their packages."""

	names = set()

	def add(name):
		parts = name.split(".")
		for index in range(1, len(parts) + 1):
			names.add(".".join(parts[:index]))

	for node in ast.walk(tree):
		if isinstance(node, ast.Import):
			for alias in node.names:
				add(alias.name)
		elif isinstance(node, ast.ImportFrom):
			base = node.module or ""
			if node.level:
				parts = package.split(".") if package else []
				if node.level > 1:
					parts = parts[:len(parts) - (node.level - 1)]
				base = ".".join(parts + ([node.module] if node.module else []))
			if base:
				add(base)
			for alias in node.names:
				if alias.name != "*":
					add(f"{base}.{alias.name}" if base else alias.name)

	return names


def restart_only(path):
	"""Whether a module can't be hot reloaded, because running it again would start a second
	thread (or process, or app), or add routes twice: it calls one of RESTART_CALLS at its top
	level. `__hot_reload__ = False` or `True` in the module decides instead."""

	try:
		tree = ast.parse(read_source(path))
	except (OSError, SyntaxError, ValueError):
		# A syntax error is reported when the module is run
		return False

	for node in tree.body:
		if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
			if any(isinstance(target, ast.Name) and target.id == "__hot_reload__" for target in node.targets):
				return not node.value.value

	return any(name in RESTART_CALLS for statement in tree.body for name in called(statement))


def called(statement):
	"""The names of what a top-level statement calls when the module is imported, decorators
	included (`@app.before_request` is called too): not what function bodies call."""

	def name(node):
		if isinstance(node, ast.Call):
			node = node.func
		if isinstance(node, ast.Attribute):
			return node.attr
		return getattr(node, "id", None)

	stack = [statement]
	while stack:
		node = stack.pop()
		if isinstance(node, ast.Lambda):
			continue
		if isinstance(node, ast.Call):
			yield name(node)
		if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
			for decorator in node.decorator_list:
				yield name(decorator)
		if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
			# Decorators and defaults run at import; the body doesn't
			stack.extend(node.decorator_list)
			stack.extend(node.args.defaults)
			stack.extend(default for default in node.args.kw_defaults if default is not None)
			continue
		stack.extend(ast.iter_child_nodes(node))


def watched(root, path):
	"""Whether a change to `path` matters: a file of a kind Domino reloads, in the app's folder,
	not in a hidden folder, a virtualenv or the like."""

	path = Path(path)
	if path.suffix not in WATCHED:
		return False

	try:
		parts = Path(os.path.realpath(path)).relative_to(root).parts
	except ValueError:
		return False

	if any(part.startswith(".") or part in SKIPPED for part in parts):
		return False

	return len(parts) < 2 or not os.path.exists(os.path.join(root, parts[0], "pyvenv.cfg"))


def is_page_file(folder, path):
	"""Whether `path` is a page, a layout or 404.py in the pages folder (see domino.pages)."""

	try:
		parts = path.relative_to(folder).parts
	except ValueError:
		return False

	return path.suffix == ".py" and not path.name.endswith("_test.py") and not any(part.startswith(("_", ".")) for part in parts)


def watch(root, stop, accept):
	"""Sets of files under `root` that `accept` takes, as they change, until `stop` is set."""

	try:
		import watchfiles
	except ImportError:
		yield from poll(root, stop, accept)
		return

	changes = watchfiles.watch(
		root, watch_filter=lambda change, path: accept(path), stop_event=stop, step=WATCH_STEP,
		ignore_permission_denied=True, raise_interrupt=False
	)
	for batch in changes:
		yield {path for _, path in batch}


def poll(root, stop, accept):
	"""watch() without watchfiles: the folder is scanned every POLL_INTERVAL seconds."""

	def scan():
		found = {}
		for folder, folders, files in os.walk(root):
			folders[:] = [name for name in folders if not name.startswith(".") and name not in SKIPPED]
			for name in files:
				path = os.path.join(folder, name)
				if not accept(path):
					continue
				try:
					stat = os.stat(path)
				except OSError:
					continue
				found[path] = (stat.st_mtime_ns, stat.st_size)
		return found

	before = scan()
	while not stop.wait(POLL_INTERVAL):
		now = scan()
		changed = {path for path in before.keys() | now.keys() if before.get(path) != now.get(path)}
		before = now
		if changed:
			yield changed


class Supervisor(BaseReload):
	"""uvicorn's reloader, except the server process decides when it needs replacing (it exits
	with RESTART_EXIT). After it fails to start (an error in app.py, say), the next change to the
	app's files starts it again."""


	def __init__(self, config, target, sockets, root):

		super().__init__(config, target, sockets)
		self.root = os.path.realpath(root)
		self.reloader_name = "Domino hot reload"


	def run(self):

		self.startup()

		while not self.should_exit.wait(CHECK_INTERVAL):
			if self.process.is_alive():
				continue
			if self.process.exitcode != RESTART_EXIT:
				changes = watch(self.root, self.should_exit, lambda path: watched(self.root, path))
				if next(changes, None) is None:
					break
				changes.close()
			self.restart()

		self.shutdown()


	def restart(self):
		"""Start a new server process. The old one has already exited, so unlike uvicorn's this
		sends it no signal (on Windows that's a Ctrl+C to the whole console, the supervisor too)."""

		self.process.join()
		self.process = get_subprocess(config=self.config, target=self.target, sockets=self.sockets)
		self.process.start()


class SubprocessConfig(uvicorn.Config):
	"""Config for a server in a process the supervisor replaces. On Windows that means asyncio's
	selector loop, as with uvicorn's own reloader: the proactor loop can't accept on a listening
	socket that an earlier process used."""

	use_subprocess = True


def serve(target, root, host="127.0.0.1", port=5000, **options):
	"""Serve the app that `target` makes (see domino.asgi.from_environ) in a process that hot
	reloads changes to the files in `root`, and is replaced when it can't."""

	config = SubprocessConfig(target, factory=True, host=host, port=port, **options)
	server = uvicorn.Server(config)
	sock = config.bind_socket()
	# Connections wait for the server process, instead of being refused while it starts (or
	# restarts)
	sock.listen(config.backlog)

	# Port 0 picks a free one; say which
	if not port:
		log(f"App: http://{host}:{sock.getsockname()[1]}/")

	Supervisor(config, server.run, [sock], root).run()
