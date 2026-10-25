"""File-based routing: each Python file in an app's pages/ folder is a page, its path the URL.

	pages/index.py         ->  /
	pages/about.py         ->  /about
	pages/users/[id].py    ->  /users/<id>
	pages/layout.py        ->  wraps every page in its folder and below
	pages/404.py           ->  the page for URLs nothing else serves
"""

import functools
import importlib.util
import inspect
import os
import re
import sys
from pathlib import Path

from . import tags as t
from .components import Document
from .core import Element
from .templates import JinjaTemplate


# [id], [int:id] and [...rest]
PARAM = re.compile(r"^\[(\.\.\.)?(?:(\w+):)?(\w+)\]$")


class PagesError(Exception):
	"""A pages/ folder Domino can't turn into routes."""


def add_pages(app, folder):
	"""Add a route for every page in `folder`, once, when the app is created."""

	folder = Path(folder).resolve()

	# Pages import the app's own modules (components, data) whatever the current folder is
	root = os.path.abspath(app.root_path)
	if root not in [os.path.abspath(path) for path in sys.path]:
		sys.path.insert(0, root)

	prefix = f"domino_pages.{app.import_name}"
	modules = {}

	def load(path):

		if path not in modules:
			modules[path] = load_module(path, module_name(prefix, folder, path))

		return modules[path]

	existing = {rule.rule: rule.endpoint for rule in app.url_map.iter_rules()}

	for path in find_pages(folder):

		relative = path.relative_to(folder).as_posix()
		rule = url_rule(path.relative_to(folder))

		if rule in app._page_rules:
			raise PagesError(f'Two pages for "{rule}": {app._page_rules[rule]} and {relative}')
		if rule in existing:
			raise PagesError(f'Two handlers for "{rule}": {relative} and the route "{existing[rule]}"')

		view = page_view(load(path), relative, rule, [load(layout) for layout in find_layouts(folder, path)])

		app.add_url_rule(rule, f"pages/{relative[:-3]}", functools.partial(app._render_view, view))
		app._page_rules[rule] = relative

	not_found = folder / "404.py"
	if not_found.is_file():
		view = page_view(load(not_found), "404.py", "", [load(layout) for layout in find_layouts(folder, not_found)])

		def page_not_found(error):

			return app._render_view(view), 404

		app.register_error_handler(404, page_not_found)


def find_pages(folder):
	"""Page files under `folder`, in a stable order. Names starting with _ or . are private,
	and files ending in _test.py are tests."""

	for path in sorted(folder.rglob("*.py")):

		parts = path.relative_to(folder).parts
		if any(part.startswith(("_", ".")) for part in parts):
			continue

		# pages/about_test.py holds the tests for pages/about.py (see domino.pytest_plugin)
		if path.name == "layout.py" or path.name.endswith("_test.py"):
			continue

		if path.name == "404.py":
			if len(parts) > 1:
				raise PagesError(f"{path.relative_to(folder).as_posix()}: 404.py only works in the pages folder itself")
			continue

		yield path


def find_layouts(folder, path):
	"""The layout.py files that wrap `path`, outermost (the pages folder's own) first."""

	layouts = []
	directory = path.parent
	while True:
		if (directory / "layout.py").is_file():
			layouts.insert(0, directory / "layout.py")
		if directory == folder:
			return layouts
		directory = directory.parent


def url_rule(relative):
	"""users/[id]/posts.py -> /users/<id>/posts; index.py is its folder's URL."""

	segments = list(relative.parts[:-1])
	if relative.stem != "index":
		segments.append(relative.stem)

	return "/" + "/".join(url_segment(segment, relative) for segment in segments)


def url_segment(segment, relative):

	if not segment.startswith("["):
		return segment

	match = PARAM.match(segment)
	if not match:
		raise PagesError(f"{relative.as_posix()}: {segment!r} isn't a URL parameter; use [name], [converter:name] or [...name]")

	catch_all, converter, name = match.groups()
	if catch_all:
		converter = "path"
	if converter:
		return f"<{converter}:{name}>"

	return f"<{name}>"


def module_name(prefix, folder, path):

	# Unique per app and file, and stable, so the reloader's child process uses the same names
	return ".".join([prefix] + list(path.relative_to(folder).with_suffix("").parts))


def load_module(path, name):

	# Imported by path: "[id]" isn't a name `import` accepts. In sys.modules, the reloader
	# watches the file for changes
	spec = importlib.util.spec_from_file_location(name, path)
	module = importlib.util.module_from_spec(spec)
	sys.modules[name] = module
	spec.loader.exec_module(module)

	return module


def page_view(module, relative, rule, layouts):
	"""A view function for one page module: its page(**params) or Page, inside its layouts."""

	params = re.findall(r"<(?:\w+:)?(\w+)>", rule)

	# A component class, not e.g. domino's own Page that `from domino import *` brings in
	component = getattr(module, "Page", None)
	if not isinstance(component, type) or not issubclass(component, Element):
		component = None

	if callable(getattr(module, "page", None)):
		make = module.page
	elif component:
		if params and not hasattr(component, "init"):
			raise PagesError(f"{relative}: Page gets the URL parameters {', '.join(params)}; add init(self, {', '.join(params)})")
		make = functools.partial(make_component, component)
	else:
		raise PagesError(f"{relative} has no page() function or Page class")

	wrappers = []
	for layout in layouts:
		if not callable(getattr(layout, "layout", None)):
			raise PagesError(f"{layout.__file__} has no layout(content) function")
		wrappers.append((layout.layout, accepted_params(layout.layout)))

	def view(**params):

		result = make(**params)

		# A whole document (Document or any <html>), a Jinja template(...) and Flask
		# responses are already complete
		if isinstance(result, (t.html, JinjaTemplate)) or not isinstance(result, (Element, str)):
			return result

		# The innermost layout wraps the page first, the pages folder's own layout last
		for layout, names in reversed(wrappers):
			kwargs = params
			if names is not None:
				kwargs = {name: value for name, value in params.items() if name in names}
			result = layout(result, **kwargs)

		# Without a layout that makes one, a component still needs a document for its events
		if isinstance(result, Element) and not isinstance(result, t.html):
			result = Document() [
				result
			]

		return result

	return view


def accepted_params(function):
	"""The keyword arguments `function` takes, or None if it takes any (**params)."""

	parameters = inspect.signature(function).parameters.values()
	if any(parameter.kind == parameter.VAR_KEYWORD for parameter in parameters):
		return None

	return {parameter.name for parameter in parameters}


def make_component(cls, **params):
	"""Page(), with the URL parameters passed to its init(self, **params)."""

	component = cls.__new__(cls)

	# Element.__init__ calls self.init() without arguments, so give it one that has them
	if params:
		component.init = functools.partial(cls.init, component, **params)

	component.__init__()
	component.__dict__.pop("init", None)

	return component
