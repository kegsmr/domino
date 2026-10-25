"""Templates: Python 3.14 template strings (t"...") parsed into Domino elements, and Jinja
templates (Flask's), found anywhere in the app's folder, with live Domino components inside."""

import os
import re
import sys
import types
import uuid
from html import unescape

from flask import current_app, has_app_context
from jinja2 import BaseLoader, TemplateNotFound
from markupsafe import Markup, escape

from . import tags
from ._components import Core, PublicSettings
from ._core import Element, Page, VOID_TAGS, current_styles, render_stack
from ._optimistic import state_names
from ._settings import script_json


class TemplateError(Exception):
	"""A template that can't be used: invalid HTML in a t-string, or two templates with one name."""


# t-strings ---------------------------------------------------------------------------------

# Interpolations are replaced by these markers while the static strings are parsed
MARKER = re.compile(r"\x00(\d+)\x00")
TAG_NAME = re.compile(r"[A-Za-z][A-Za-z0-9:_.-]*|\x00(\d+)\x00")
CLOSE_TAG = re.compile(r"</\s*([A-Za-z][A-Za-z0-9:_.-]*|\x00\d+\x00)\s*>")
ATTRIBUTE_NAME = re.compile(r"[^\s\x00\"'<>/=]+")
UNQUOTED_VALUE = re.compile(r"(?:[^\s>/]|/(?!>))+")
SPACE = re.compile(r"\s*")
# HTML whitespace; not \xa0 from &nbsp;
SPACES = " \t\n\r\f"
WHITESPACE = re.compile(f"[{SPACES}]+")

# Content is text up to the closing tag: raw for script and style, with entities for these
RAW_TEXT = ("script", "style")
ESCAPABLE_RAW_TEXT = ("textarea", "title")

TAG_CLASSES = {name: getattr(tags, name) for name in tags.TAGS}

# template.strings -> parsed nodes; each distinct template is parsed once
_cache = {}


class Node:
	"""A parsed element, built into a Domino element each time its template renders."""

	__slots__ = ("tag", "cls", "component", "close", "static", "dynamic", "children", "line", "raw", "pre")


	def __init__(self, tag, line):

		self.tag = tag
		self.cls = None
		self.component = None  # interpolation index for <{Component}>
		self.close = None  # and for its </{Component}>
		# Attributes without interpolations, and None in the place of those with one: the
		# render fills them in, and the dict keeps the order they were written in
		self.static = {}
		self.dynamic = []  # (name, index or parts); name None for a spread <div {attrs}>
		self.children = []  # str (text), tuple (text with interpolations) or Node
		self.line = line
		self.raw = None
		self.pre = False


def html(template):
	"""Build Domino elements from a t-string: html(t"<p>Count: {self.count}</p>").

	Returns the element when the template has one root element, otherwise a list of children.
	"""

	try:
		from string.templatelib import Template
	except ImportError:
		raise RuntimeError(
			f"domino.html() needs Python 3.14 or newer for template strings (t\"...\"); this is "
			f"Python {sys.version_info.major}.{sys.version_info.minor}. Use tag classes or Jinja "
			"templates (domino.template) instead."
		) from None

	# An f-string would arrive here already joined, with its values unescaped
	if not isinstance(template, Template):
		raise TypeError(f"html() takes a template string, t\"...\", not {type(template).__name__}")

	nodes = _cache.get(template.strings)
	if nodes is None:
		nodes = _parse(template.strings)
		_cache[template.strings] = nodes

	values = [_value(interpolation) for interpolation in template.interpolations]
	children = _build(nodes, values, None)

	if len(children) == 1 and isinstance(children[0], Element):
		return children[0]

	return children


def _value(interpolation):

	value = interpolation.value
	if interpolation.conversion == "r":
		value = repr(value)
	elif interpolation.conversion == "s":
		value = str(value)
	elif interpolation.conversion == "a":
		value = ascii(value)
	if interpolation.format_spec:
		value = format(value, interpolation.format_spec)

	return value


def _parse(strings):

	source = "".join(f"{string}\x00{index}\x00" for index, string in enumerate(strings[:-1]))

	return Parser(source + strings[-1]).parse()


def _parts(text):
	"""Split text with markers into static strings and interpolation indexes."""

	pieces = MARKER.split(text)
	parts = []
	for index, piece in enumerate(pieces):
		if index % 2:
			parts.append(int(piece))
		elif piece:
			parts.append(piece)

	return parts


class Parser:


	def __init__(self, source):

		self.source = source
		self.pos = 0
		self.root = Node(None, 1)
		self.stack = [self.root]
		self.text = []  # text seen since the last tag


	def line(self, pos=None):

		if pos is None:
			pos = self.pos

		return self.source.count("\n", 0, pos) + 1


	def error(self, message, pos=None):

		return TemplateError(f"line {self.line(pos)}: {message}")


	def parse(self):

		source = self.source
		while self.pos < len(source):
			start = source.find("<", self.pos)
			if start == -1:
				self.text.append(source[self.pos:])
				break
			self.text.append(source[self.pos:start])
			self.pos = start
			following = source[start + 1:start + 2]

			if source.startswith("<!--", start):
				end = source.find("-->", start + 4)
				if end == -1:
					raise self.error("comment is never closed")
				self.pos = end + 3
			elif following == "/":
				self.close_tag()
			elif following in ("!", "?"):
				# <!DOCTYPE ...> and the like; Document adds the doctype
				end = source.find(">", start)
				if end == -1:
					raise self.error("<! is never closed")
				self.pos = end + 1
			elif TAG_NAME.match(source, start + 1):
				self.open_tag()
			else:
				# A "<" that doesn't start a tag, as in "a < b"
				self.text.append("<")
				self.pos += 1

		self.flush_text()
		if len(self.stack) > 1:
			node = self.stack[-1]
			raise TemplateError(f"line {node.line}: <{node.tag}> is never closed")
		_trim(self.root.children)

		return self.root.children


	def flush_text(self):

		text = "".join(self.text)
		self.text = []
		if not text:
			return

		parent = self.stack[-1]
		if not parent.pre:
			# Whitespace that only lays out the template isn't content
			if not text.strip(SPACES) and "\n" in text:
				return
			text = WHITESPACE.sub(" ", text)

		parts = [_unescape_part(part) for part in _parts(text)]
		if len(parts) == 1 and isinstance(parts[0], str):
			parent.children.append(parts[0])
		elif parts:
			parent.children.append(tuple(parts))


	def open_tag(self):

		source = self.source
		start = self.pos
		match = TAG_NAME.match(source, start + 1)
		self.pos = match.end()
		self.check_boundary("a tag name")
		self.flush_text()

		node = Node(match.group(0), self.line(start))
		if match.group(1) is not None:
			node.component = int(match.group(1))
			node.tag = "{...}"
		else:
			lower = node.tag.lower()
			node.cls = TAG_CLASSES.get(lower)
			if node.cls is not None:
				node.tag = lower

		self_closing = self.attributes(node)

		parent = self.stack[-1]
		parent.children.append(node)
		node.pre = parent.pre or node.tag == "pre"

		if self_closing or (node.component is None and node.tag in VOID_TAGS):
			return

		if node.tag in RAW_TEXT or node.tag in ESCAPABLE_RAW_TEXT:
			self.raw_text(node)
			return

		self.stack.append(node)


	def check_boundary(self, what):

		following = self.source[self.pos:self.pos + 1]
		if following and not following.isspace() and following not in "/>":
			raise self.error(f"an interpolation can't be part of {what}")


	def attributes(self, node):
		"""Parse the attributes of the tag being opened; True if it ends with />."""

		source = self.source
		while True:
			self.pos = SPACE.match(source, self.pos).end()
			if self.pos >= len(source):
				raise TemplateError(f"line {node.line}: <{node.tag} is never closed with >")
			if source.startswith("/>", self.pos):
				self.pos += 2
				return True
			if source[self.pos] == ">":
				self.pos += 1
				return False

			marker = MARKER.match(source, self.pos)
			if marker:
				# <div {attrs}> spreads a dict of attributes
				self.pos = marker.end()
				self.check_boundary("an attribute name")
				node.dynamic.append((None, int(marker.group(1))))
				continue

			match = ATTRIBUTE_NAME.match(source, self.pos)
			if not match:
				raise self.error(f"unexpected {source[self.pos]!r} in <{node.tag}>")
			self.pos = match.end()
			if source[self.pos:self.pos + 1] == "\x00":
				raise self.error("an interpolation can't be part of an attribute name")

			# Attribute names are Domino keyword names: aria-label -> aria_label, class -> class_
			name = match.group(0).replace("-", "_")
			if name == "class":
				name = "class_"

			after = SPACE.match(source, self.pos).end()
			if source[after:after + 1] != "=":
				node.static[name] = True
				continue
			self.pos = SPACE.match(source, after + 1).end()
			self.attribute_value(node, name)


	def attribute_value(self, node, name):

		source = self.source
		quote = source[self.pos:self.pos + 1]
		if quote in ("\"", "'"):
			end = source.find(quote, self.pos + 1)
			if end == -1:
				raise self.error(f"the value of {name} in <{node.tag}> is never closed")
			text = source[self.pos + 1:end]
			self.pos = end + 1
		else:
			match = MARKER.match(source, self.pos) or UNQUOTED_VALUE.match(source, self.pos)
			if not match:
				raise self.error(f"{name}= in <{node.tag}> has no value")
			text = match.group(0)
			self.pos = match.end()

		parts = _parts(text)
		if not parts:
			node.static[name] = ""
		elif len(parts) == 1 and isinstance(parts[0], int):
			node.static[name] = None
			node.dynamic.append((name, parts[0]))
		elif all(isinstance(part, str) for part in parts):
			node.static[name] = unescape("".join(parts))
		else:
			node.static[name] = None
			node.dynamic.append((name, [_unescape_part(part) for part in parts]))


	def raw_text(self, node):

		source = self.source
		end = re.compile(f"</\\s*{node.tag}\\s*>", re.IGNORECASE).search(source, self.pos)
		if end is None:
			raise TemplateError(f"line {node.line}: <{node.tag}> is never closed")
		text = source[self.pos:end.start()]
		self.pos = end.end()

		node.raw = node.tag
		parts = _parts(text)
		if node.tag in ESCAPABLE_RAW_TEXT:
			node.raw = None
			parts = [_unescape_part(part) for part in parts]
		if node.tag == "title":
			parts = [_collapse(part) for part in parts]
		if not parts:
			return

		node.children.append(tuple(parts))
		# What a textarea holds is its value, spaces included
		if node.tag != "textarea":
			_trim(node.children)


	def close_tag(self):

		match = CLOSE_TAG.match(self.source, self.pos)
		if not match:
			raise self.error("malformed closing tag")
		self.flush_text()

		name = match.group(1)
		node = self.stack[-1]
		marker = MARKER.fullmatch(name)
		if node is self.root:
			raise self.error(f"</{_shown(name)}> closes nothing")
		if marker and node.component is not None:
			node.close = int(marker.group(1))
		elif marker or node.component is not None or name.lower() != node.tag.lower():
			raise self.error(f"</{_shown(name)}> doesn't match <{node.tag}> from line {node.line}")

		self.pos = match.end()
		self.stack.pop()
		if not node.pre:
			_trim(node.children)


def _shown(name):

	if MARKER.fullmatch(name):
		return "{...}"

	return name


def _collapse(part):

	if isinstance(part, str):
		return WHITESPACE.sub(" ", part)

	return part


def _unescape_part(part):

	if isinstance(part, str):
		return unescape(part)

	return part


def _trim(children):
	"""Drop the space at the start and end of an element's content."""

	for index, strip in ((0, str.lstrip), (-1, str.rstrip)):
		if not children:
			return
		child = children[index]
		if isinstance(child, str):
			child = strip(child, SPACES)
			if child:
				children[index] = child
			else:
				children.pop(index)
		elif isinstance(child, tuple) and isinstance(child[index], str):
			parts = list(child)
			parts[index] = strip(parts[index], SPACES)
			if not parts[index]:
				parts.pop(index)
			children[index] = tuple(parts)


def _build(items, values, raw):

	out = []
	for item in items:
		kind = type(item)
		if kind is str:
			out.append(item)
		elif kind is tuple:
			_text(item, values, out, raw)
		else:
			out.append(_element(item, values))

	return out


def _text(parts, values, out, raw):

	buffer = []
	for part in parts:
		if type(part) is str:
			buffer.append(part)
		elif raw == "script":
			# Values go into scripts as JSON, which can't end the script early
			buffer.append(script_json(values[part]))
		elif raw == "style":
			buffer.append(str(values[part]).replace("<", "\\3c "))
		else:
			_add(values[part], buffer, out)

	_flush(buffer, out)


def _add(value, buffer, out):

	if value is None or value is False:
		return

	if isinstance(value, (list, tuple, types.GeneratorType)):
		for item in value:
			_add(item, buffer, out)
		return

	if isinstance(value, Element) or (isinstance(value, type) and issubclass(value, Element)):
		_flush(buffer, out)
		out.append(value)
		return

	if isinstance(value, Markup):
		buffer.append(value)
		return

	buffer.append(str(value))


def _flush(buffer, out):

	if not buffer:
		return

	# Markup.join escapes the plain strings and keeps the Markup as it is
	if any(isinstance(text, Markup) for text in buffer):
		text = Markup("").join(buffer)
	else:
		text = "".join(buffer)
	buffer.clear()

	if text:
		out.append(text)


def _element(node, values):

	kwargs = dict(node.static)
	for name, value in node.dynamic:
		if name is None:
			spread = values[value]
			if not isinstance(spread, dict):
				raise TemplateError(f"line {node.line}: <{node.tag} {{...}}> needs a dict of attributes, got {spread!r}")
			for key, item in spread.items():
				kwargs[key.replace("-", "_")] = item
		elif type(value) is int:
			kwargs[name] = values[value]
		else:
			kwargs[name] = "".join(_attribute_text(part, values) for part in value)

	if node.component is None:
		if node.cls is not None:
			element = node.cls()
		else:
			element = Element(node.tag)
		if kwargs:
			element.configure(**kwargs)
	else:
		element = _component(node, values, kwargs)

	if node.children:
		children = _build(node.children, values, node.raw)
		if children:
			element.set_children(children)

	return element


def _attribute_text(part, values):

	if type(part) is str:
		return part

	value = values[part]
	if value is None or value is False:
		return ""

	return str(value)


def _component(node, values, kwargs):

	component = values[node.component]
	if node.close is not None and values[node.close] is not component:
		raise TemplateError(f"line {node.line}: </{{...}}> closes a different component than <{{{component!r}}}>")

	if not callable(component):
		raise TemplateError(f"line {node.line}: <{{...}}> needs a component class, got {component!r}")

	element = component(**kwargs)
	if not isinstance(element, Element):
		raise TemplateError(f"line {node.line}: <{{{component!r}}}> made {element!r}, not an element")

	return element


# Jinja -------------------------------------------------------------------------------------

# Folders never searched for templates
SKIPPED_FOLDERS = ("node_modules", "static", "__pycache__", "site-packages")

# A file that starts (after comments and an optional {# domino #}) with a capitalized tag defines
# components; see domino._dtemplates
DEFINITION_START = re.compile(r"\A(?:\s|<!--.*?-->|\{#\s*domino\s*#\})*<(?:component|layout)\b", re.S)


class TemplateFinder(BaseLoader):
	"""Finds .html templates anywhere under the app's folder by file name, like Meteor.

	Templates in the app's templates/ folder are left to Flask's own loader. The index is built
	at startup, so two templates with one name are an error straight away.
	"""


	def __init__(self, root, template_folder=None, pages=None, setting=None):

		self.root = os.path.abspath(root)
		self.template_folder = None
		if template_folder:
			self.template_folder = os.path.join(self.root, template_folder)
		# Templates in pages/ are pages, found by their URL, so names there may repeat
		self.pages = os.path.join(self.root, pages) if pages else None
		if self.pages:
			from ._dtemplates import pages_folders
			pages_folders.add(self.pages)
		self.setting = setting  # {"templates": "jinja"} reads every file as Jinja
		self.paired = {}  # paired component templates, by path
		self.ambiguous = {}  # names of several pages' templates -> their paths
		self.stale = False  # definitions to find again (hot reloading)
		self.warned = False  # about definitions without a class
		self.index = self.scan()


	def is_page(self, path):
		"""Whether `path` is a page template: in the pages folder, without a .py of the same name
		(whose components' markup it would be). A capitalized tag at a page's top level uses that
		component (<Layout title="About">...</Layout>) rather than defining it."""

		return is_page_template(path, self.pages)


	def skip(self, folder, name):

		if name.startswith(".") or name in SKIPPED_FOLDERS:
			return True

		path = os.path.join(folder, name)

		# A virtualenv in the app's folder has nothing of the app's own
		return path == self.template_folder or os.path.exists(os.path.join(path, "pyvenv.cfg"))


	def scan(self):

		found = {}
		files_found = []
		for folder, folders, files in os.walk(self.root):
			folders[:] = sorted(name for name in folders if not self.skip(folder, name))
			for name in sorted(files):
				if name.endswith((".html", ".jinja")):
					files_found.append(os.path.join(folder, name))

		# Files that define components (<TodoList>...</TodoList>) are found by the names they define
		self.definitions = self.find_definitions(files_found)
		defining = {path for paths in self.definitions.values() for path in paths}

		self.ambiguous = {}
		in_pages = {}
		for path in files_found:
			if path in defining:
				continue
			name = os.path.basename(path)
			if self.pages and path.startswith(self.pages + os.sep):
				in_pages.setdefault(name, []).append(path)
			else:
				found.setdefault(name, []).append(path)
		for name, paths in in_pages.items():
			if len(paths) > 1 and name not in found:
				self.ambiguous[name] = paths
			else:
				found.setdefault(name, []).extend(paths)

		# Flask's loader would win silently, so a template there with the same name is ambiguous too
		if self.template_folder:
			for name, paths in found.items():
				path = os.path.join(self.template_folder, name)
				if os.path.isfile(path):
					paths.insert(0, path)

		duplicates = {name: paths for name, paths in found.items() if len(paths) > 1}
		if duplicates:
			lines = []
			for name, paths in sorted(duplicates.items()):
				lines.append(f"{name}:")
				lines.extend(f"    {path}" for path in paths)
			raise TemplateError(
				"Templates are found by file name, so these names must be unique; rename one of each:\n"
				+ "\n".join(lines)
			)

		return {name: paths[0] for name, paths in found.items()}


	def find_definitions(self, paths):
		"""{component name: [files defining it]} from the files whose top level is component
		definitions (<TodoList>...</TodoList>). Pages, Jinja templates and partials are skipped."""

		from . import _dtemplates as dtemplates

		definitions = {}
		for path in paths:
			if not path.endswith(".html") or self.is_page(path):
				continue
			with open(path, encoding="utf-8") as file:
				source = file.read()
			if not DEFINITION_START.match(source) or dtemplates.source_format(path, source, self.setting) != "domino":
				continue
			for name in dtemplates.definitions_in(path):
				definitions.setdefault(name, []).append(path)

		# Two classes with one name, in different modules, can each have the template next to
		# their module; any other repeat is a mistake
		for name, found in sorted(definitions.items()):
			if len(found) > 1 and not all(os.path.isfile(os.path.splitext(path)[0] + ".py") for path in found):
				files = "\n".join(f"    {dtemplates.shown_path(path)}" for path in found)
				raise TemplateError(
					f"<{name}> is defined in more than one file. Each component has one definition; "
					f"remove or rename one of them:\n{files}"
				)

		return definitions


	def current_definitions(self):

		if self.stale:
			self.stale = False
			self.warned = False
			self.index = self.scan()

		return self.definitions


	def path(self, name, environment=None, auto_reload=False):
		"""The file of the template called `name`, or None."""

		if name in self.ambiguous:
			files = "\n".join(f"    {path}" for path in self.ambiguous[name])
			raise TemplateError(f"Several templates are called {name}; pages are found by their URL, so use a page's own path, or rename one:\n{files}")

		path = self.paired.get(name) or self.index.get(name)
		if path is None and self.template_folder:
			candidate = os.path.join(self.template_folder, name)
			if os.path.isfile(candidate):
				path = candidate

		# While debugging, a template added since startup is found without a restart
		if path is None and auto_reload:
			self.index = self.scan()
			path = self.index.get(name)

		# A file of component definitions, which rendering says isn't a page
		if path is None:
			path = next((path for paths in self.definitions.values() for path in paths if os.path.basename(path) == name), None)

		return path


	def get_source(self, environment, template):

		path = self.paired.get(template) or self.index.get(template)

		# While debugging, a template added since startup is found without a restart
		if path is None and environment.auto_reload:
			self.index = self.scan()
			path = self.index.get(template)
		if path is None:
			raise TemplateNotFound(template)

		with open(path, encoding="utf-8") as file:
			source = file.read()
		mtime = os.path.getmtime(path)

		def uptodate():

			try:
				return os.path.getmtime(path) == mtime
			except OSError:
				return False

		return source, path, uptodate


	def list_templates(self):

		return sorted(self.index)


def template(name, /, **context):
	"""A template as an element: templates/<name>, or <name> anywhere in the app's folder. A Domino
	template (see domino._dtemplates) shows components as tags, <Counter />, found in the context,
	the calling module, or the app's components; a Jinja one with {{ component(Counter) }}.
	"""

	try:
		app = _app()
	except RuntimeError:
		app = None

	finder = getattr(app, "template_finder", None)
	path = None
	if finder is not None:
		path = finder.path(name, auto_reload=bool(app.debug or app.config.get("TEMPLATES_AUTO_RELOAD")))

	if path is not None and template_format(path) != "jinja":
		from ._dtemplates import DominoTemplate
		return DominoTemplate(path, context, sys._getframe(1).f_globals)

	return JinjaTemplate(name, **context)


def page_template(path, /, **context):
	"""A template in pages/ as its page, with the URL's parameters as its context."""

	if template_format(path) == "jinja":
		_app().template_finder.paired[path] = path
		return JinjaTemplate(path, **context)

	from ._dtemplates import DominoTemplate

	return DominoTemplate(path, context)


def template_format(path):
	""""components", "domino" or "jinja" for a template file (see dtemplates.file_format)."""

	from ._dtemplates import file_format

	setting = None
	try:
		setting = (getattr(_app(), "settings", None) or {}).get("templates")
	except RuntimeError:
		pass

	return file_format(path, setting)


class JinjaTemplate(Element):


	def __init__(self, name, /, **context):

		super().__init__("")

		self.name = name
		self.context = context


	def _render(self, level=0, indent=4):

		html = _app().jinja_env.get_template(self.name).render(self.context)

		# Returned from a route, the template is the page: it needs the page id and core.js
		if self.__attributes__:
			html = _as_page(html, self.__attributes__)

		return html


def _as_page(html, attributes):

	marks = " ".join(f"{key.replace('_', '-')}=\"{escape(value)}\"" for key, value in attributes.items())

	tag = re.search(r"<(html|body)\b", html, re.IGNORECASE)
	if tag:
		html = f"{html[:tag.end()]} {marks}{html[tag.end():]}"
	else:
		html = f"<div {marks}>\n{html}\n</div>"

	end = re.search(r"</head>|</body>", html, re.IGNORECASE)

	# Component CSS goes before the template's first stylesheet, so its own rules still win
	# (as in a Document)
	styles = current_styles()
	if styles is not None:
		mark = styles.place(1, "\t")
		first = re.search(r"<(style|link)\b", html[:end.start()] if end else html, re.IGNORECASE)
		if first:
			html = f"{html[:first.start()]}{mark}{html[first.start():]}"
			end = re.search(r"</head>|</body>", html, re.IGNORECASE)
		elif end:
			html = f"{html[:end.start()]}{mark}{html[end.start():]}"
			end = re.search(r"</head>|</body>", html, re.IGNORECASE)
		else:
			html += mark

	if "/_domino/core" in html:
		return html

	scripts = PublicSettings()._render() + Core()._render()
	if end is None:
		return html + scripts

	return f"{html[:end.start()]}{scripts}{html[end.start():]}"


def _app():

	if has_app_context():
		return current_app._get_current_object()

	# A component refreshed from a background thread renders outside any request
	app = getattr(Page.current(), "app", None)
	if app is None:
		raise RuntimeError("Rendering a Jinja template needs a Domino app (render it in a request)")

	return app


def component(cls, *args, **kwargs):
	"""For Jinja templates: {{ component(Counter, title="x") }} renders a live component."""

	element = cls
	if not isinstance(cls, Element):
		element = cls(*args, **kwargs)

	return Markup(element.__html__())


def on(event=None, callback=None, debounce=None, **events):
	"""For Jinja templates: <button {{ on(click=increment) }}> binds events like on_click=.

	Several at once: on(input=search, change=save, debounce=250).
	"""

	if event is not None:
		events = {event: callback, **events}

	# Inside a component's render, number events per component, as Element.bind does, so
	# they keep their ids across re-renders and go when the component is re-rendered
	stack = render_stack()
	owner = None
	if stack:
		owner = stack[-1][0]

	page = Page.current()
	ids = []
	marks = []
	for name, handler in events.items():
		name = name.lower()
		if owner is not None:
			event_id = owner._event_id("event", name)
			page.register(event_id, owner, handler)
		else:
			event_id = f"event-{uuid.uuid4()}-{name}"
			page.register(event_id, getattr(handler, "__self__", None), handler)
		ids.append(event_id)
		if debounce:
			marks.append(f" data-debounce-{name}=\"{int(debounce)}\"")

	return Markup(f"data-event-id=\"{' '.join(ids)}\"" + "".join(marks))


def is_page_template(path, pages):

	if not pages:
		return False
	path = os.path.abspath(path)

	return path.startswith(os.path.abspath(pages) + os.sep) and not os.path.exists(os.path.splitext(path)[0] + ".py")


def snake_case(name):

	return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name).lower()


def paired_template(cls):
	"""The template file of a component without render(), or None: the file defining it
	(<TodoList>...</TodoList>, see domino._dtemplates), the one next to its module winning when
	several classes share the name; or a Jinja template next to its module named after the class
	(TodoList -> todo_list.html) or the module (counter.py -> counter.html)."""

	# A component that is only markup (see dtemplates.MarkupComponent)
	definition = cls.__dict__.get("_domino_definition")
	if definition is not None:
		return definition

	if cls.__module__.split(".")[0] == "domino":
		return None

	path = getattr(sys.modules.get(cls.__module__), "__file__", None)
	if not path:
		return None

	folder, filename = os.path.split(os.path.abspath(path))
	stem = os.path.splitext(filename)[0]

	# The older way: a Jinja template, the markup as it is (not inside <TodoList>)
	for name in (snake_case(cls.__name__), stem):
		for extension in (".html", ".jinja"):
			candidate = os.path.join(folder, f"{name}{extension}")
			if os.path.isfile(candidate) and template_format(candidate) != "components":
				return candidate

	beside = os.path.join(folder, f"{stem}.html")
	try:
		finder = getattr(_app(), "template_finder", None)
	except RuntimeError:
		finder = None
	if finder is not None:
		defined = finder.current_definitions().get(cls.__name__, ())
		if beside in defined:
			return beside
		if defined:
			return defined[0]

	# A file of definitions next to the module, without this class's: rendering says so
	if os.path.isfile(beside) and template_format(beside) == "components":
		return beside

	return None


def render_paired(element, path):
	"""Render a component with its paired template; the HTML becomes its children."""

	if template_format(path) == "components":
		from ._dtemplates import render_component
		return render_component(element, path)

	app = _app()
	finder = getattr(app, "template_finder", None)
	if finder is None:
		raise RuntimeError(f"{type(element).__name__} has a paired template, which needs a Domino app")
	finder.paired[path] = path

	# State values and methods by name; Jinja keeps `self` for blocks, so the component is `this`
	context = {}
	for base in reversed(type(element).__mro__):
		if base is object or base is Element or base.__module__ == "domino.tags":
			continue
		for name, value in vars(base).items():
			if isinstance(value, types.FunctionType) and not name.startswith("_") and name != "init":
				context[name] = getattr(element, name)
	for name in state_names(type(element)):
		context[name] = getattr(element, name)
	context["this"] = element

	return Markup(app.jinja_env.get_template(path).render(context))
