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

from flask import abort

from . import tags as t
from .components import Document
from .core import Element
from .templates import JinjaTemplate


# [id], [int:id] and [...rest]
PARAM = re.compile(r"^\[(\.\.\.)?(?:(\w+):)?(\w+)\]$")


class PagesError(Exception):
	"""A pages/ folder Domino can't turn into routes."""


class PageRoute:
	"""The view of a page's URL rule. Hot reloading (see domino.hot) gives it a new view when the
	page changes, since Flask can't replace or remove a rule; with none (the page's file was
	deleted) it answers 404. `modules` are the names of the page's module and its layouts'."""


	def __init__(self):

		self.view = None
		self.modules = ()


	def __call__(self, **params):

		if self.view is None:
			abort(404)

		return self.view(**params)


def add_pages(app, folder, reload=False):
	"""Add a route for every page in `folder`, when the app is created. Hot reloading calls this
	again with reload=True, after reloading the modules that changed: pages get their new views,
	new pages get routes, and the routes of pages deleted since answer 404."""

	folder = Path(folder).resolve()
	app._pages_folder = folder

	# Pages import the app's own modules (components, data) whatever the current folder is
	root = os.path.abspath(app.root_path)
	if root not in [os.path.abspath(path) for path in sys.path]:
		sys.path.insert(0, root)

	prefix = f"domino_pages.{app.import_name}"
	modules = {}

	def load(path):

		if path not in modules:
			name = module_name(prefix, folder, path)
			# Reloading uses the modules already imported (and reloaded); new pages are imported
			modules[path] = (reload and sys.modules.get(name)) or load_module(path, name)

		return modules[path]

	existing = {rule.rule: rule.endpoint for rule in app.url_map.iter_rules()}

	# Every view first, so a page that can't be served leaves the routes as they were
	found = {}
	for path in find_pages(folder):

		relative = path.relative_to(folder).as_posix()
		rule = url_rule(path.relative_to(folder))

		if rule in found:
			raise PagesError(f'Two pages for "{rule}": {found[rule][0]} and {relative}')
		if rule in existing and rule not in app._page_routes:
			raise PagesError(f'Two handlers for "{rule}": {relative} and the route "{existing[rule]}"')

		layouts = [(load(code) if code else None, markup) for code, markup in find_layouts(folder, path)]
		names = tuple(module.__name__ for module, _ in layouts if module is not None)
		if path.suffix == ".html":
			view = template_page_view(path, relative, layouts)
			found[rule] = (relative, view, names)
			continue
		view = page_view(load(path), relative, rule, layouts)
		found[rule] = (relative, view, (load(path).__name__,) + names)

	not_found = folder / "404.py"
	if not_found.is_file():
		layouts = [(load(code) if code else None, markup) for code, markup in find_layouts(folder, not_found)]
		view = page_view(load(not_found), "404.py", "", layouts)
		found[None] = ("404.py", view, (load(not_found).__name__,) + tuple(module.__name__ for module, _ in layouts if module is not None))

	for rule, (relative, view, names) in found.items():

		route = app._page_routes.get(rule)
		if route is None:
			route = app._page_routes[rule] = PageRoute()
			if rule is None:
				app.register_error_handler(404, functools.partial(page_not_found, app, route))
			else:
				app.add_url_rule(rule, f"pages/{relative.rsplit('.', 1)[0]}", functools.partial(app._render_view, route))
		route.view = view
		route.modules = names
		if rule is not None:
			app._page_rules[rule] = relative

	# Deleted since the app was created (hot reloading): Flask keeps the rule, which answers 404
	for rule, route in app._page_routes.items():
		if rule not in found:
			route.view = None
			app._page_rules.pop(rule, None)


def page_not_found(app, route, error):

	# Without 404.py (deleted while hot reloading), Flask's own 404
	if route.view is None:
		return error

	return app._render_view(route), 404


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

	yield from find_template_pages(folder)


def find_template_pages(folder):
	"""Templates in `folder` that are pages: about.html is /about, like about.py, unless there's an
	about.py (then about.html is its components' template) or it defines components."""

	from .templates import template_format

	for path in sorted(folder.rglob("*.html")):

		parts = path.relative_to(folder).parts
		if any(part.startswith(("_", ".")) for part in parts) or path.name in ("404.html", "layout.html"):
			continue
		if path.with_suffix(".py").exists() or template_format(str(path)) == "components":
			continue

		yield path


def find_layouts(folder, path):
	"""The layouts that wrap `path`, outermost (the pages folder's own) first: per folder,
	(its layout.py or None, its layout.html or None)."""

	layouts = []
	directory = path.parent
	while True:
		code, markup = directory / "layout.py", directory / "layout.html"
		if code.is_file() or markup.is_file():
			layouts.insert(0, (code if code.is_file() else None, str(markup) if markup.is_file() else None))
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

	return layout_view(make, layouts)


def template_page_view(path, relative, layouts):
	"""The view of a template in pages/: the template, with the URL's parameters as its context."""

	from .templates import page_template

	return layout_view(functools.partial(page_template, str(path)), layouts)


def layout_view(make, layouts):

	wrappers = []
	for module, markup in layouts:
		function = getattr(module, "layout", None) if module is not None else None
		if module is not None and not callable(function):
			if markup is None:
				raise PagesError(f"{module.__file__} has no layout(content) function")
			raise PagesError(f"{module.__file__} has no layout() function giving layout.html its values")
		wrappers.append((function, accepted_params(function) if function else None, markup))

	def view(**params):

		result = make(**params)

		# A whole document (Document or any <html>), a Jinja template(...), a Domino template with
		# <html>, <head> or <body>, and Flask responses are already complete
		if is_complete(result):
			return result

		# The innermost layout wraps the page first, the pages folder's own layout last
		for index, (layout, names, markup) in reversed(list(enumerate(wrappers))):
			kwargs = params
			if names is not None:
				kwargs = {name: value for name, value in params.items() if name in names}
			if markup is None:
				result = layout(result, **kwargs)
			else:
				result = template_layout(markup, layout, names, result, params, kwargs, wrappers[:index])

		# Without a layout that makes one, a component still needs a document for its events
		if isinstance(result, Element) and not isinstance(result, t.html) and not getattr(result, "is_document", False):
			result = Document() [
				result
			]

		return result

	return view


def is_complete(result):
	"""Whether a page's result is already the whole response, which layouts leave alone."""

	return (
		isinstance(result, (t.html, JinjaTemplate))
		or getattr(result, "is_document", False)
		or not isinstance(result, (Element, str))
	)


def template_layout(markup, layout, names, content, params, kwargs, outer):
	"""layout.html around `content`, which goes where it has <slot />. Its values are the URL's
	parameters, and what layout() returns when there's a layout.py next to it."""

	from .dtemplates import DominoTemplate

	values = dict(params)
	if layout is not None:
		if names is None or "content" in names:
			kwargs = dict(kwargs, content=content)
		returned = layout(**kwargs)
		if returned is not None and not isinstance(returned, dict):
			raise PagesError(
				f"layout() next to {os.path.basename(markup)} returns the template's values as a dict "
				f"(or nothing), not {type(returned).__name__}; the page goes where the template has <slot />"
			)
		values.update(returned or {})

	element = DominoTemplate(markup, values, slot=[content])

	# Only the outermost layout can be the document; the others go in its <slot />
	if outer and element.is_document:
		first = next((markup or module_file(function)) for function, _, markup in outer)
		raise PagesError(
			f"{markup} is a whole document (<html>), but it's inside {first}; only the outermost layout "
			"can be, so leave out <html>, <head> and <body> here"
		)

	return element


def module_file(function):

	return getattr(sys.modules.get(getattr(function, "__module__", "")), "__file__", None) or "a layout"


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
