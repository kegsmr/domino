"""Windows: <window name="Settings" width="420" height="560">...</window>, a component shown in a window
of its own. A click opens it (<button open-window="Settings">, or Settings.open(tab="audio") in a
handler); in a desktop app (domino desktop) it's a native window, in a browser a dialog on the page.

A window is served at /_domino/window/<Name>, its values in the query string, so it is a page of its
own: its State is its own, and what windows show from a Collection or a module's State updates in
every window, as it does in every tab.
"""

import json
import urllib.parse

from flask import abort, g, has_request_context, request

import domino.tags as t


# A <window>'s options, and the kind of value each takes (not attributes of its element)
OPTIONS = {
	"title": str,
	"width": int,
	"height": int,
	"min-width": int,
	"min-height": int,
	"resizable": bool,
	"on-top": bool,
	"maximized": bool,
	"remember": bool,
	"main": bool,
}

ROUTE = "/_domino/window/<name>"


class WindowError(Exception):
	pass


class Window(t.div):
	"""A window's class, for its State, helpers and handlers: class Settings(Window), with
	<window name="Settings"> as its markup. Settings.open(tab="audio") opens it from a handler, and
	self.close() closes it."""

	_domino_base = True


	@classmethod
	def open(cls, **values):

		open_window(cls.__name__, **values)


	def close(self):

		close_window()


	def configure(self, **kwargs):

		# What it's opened with (Help.open(topic="keys")) is its values, declared or not; only
		# what HTML attributes look like stays for its element
		declared = dir(type(self))
		for key in list(kwargs):
			if key not in declared and key not in ("class_", "id", "style", "debounce") and not key.startswith(("on_", "data_", "aria_")):
				self.__dict__[key] = kwargs.pop(key)

		return super().configure(**kwargs)


def _markup_window():

	from .dtemplates import MarkupComponent

	class MarkupWindow(MarkupComponent, Window):
		"""The base of a window with no class of its own (see dtemplates.markup_component)."""

		_domino_base = True

	return MarkupWindow


def definition(name):
	"""The <window name="..."> definition called `name`."""

	from .dtemplates import definition_named

	found = definition_named(name)
	if found is None or found.kind != "window":
		raise WindowError(f"No window called {name}: define it with <window name=\"{name}\">...</window>")

	return found


def window_url(name, values):

	url = f"/_domino/window/{name}"
	if values:
		url += "?" + urllib.parse.urlencode({"values": json.dumps(values)})

	return url


def open_window(name, **values):
	"""Open the window called `name` (<window name="Settings">) once this event's handler is done,
	given `values` (Settings.open(tab="audio") gives it tab="audio"). Only in an event handler."""

	if isinstance(name, type):
		name = name.__name__

	if not (has_request_context() and "domino_windows" in g):
		raise WindowError("open_window() opens a window from an event handler (a click, say)")

	try:
		json.dumps(values)
	except TypeError:
		raise WindowError(f"{name}'s values are sent through the browser, so they must be JSON: strings, numbers, lists and dicts") from None

	options = dict(definition(name).window)
	g.domino_windows.append({"name": name, "url": window_url(name, values), **options})


def close_window():
	"""Close the window whose event this is, once its handler is done. In a browser, the page
	closes the dialog it's in, or the tab if a script opened it."""

	if not (has_request_context() and "domino_windows" in g):
		raise WindowError("close_window() closes the window from an event handler (a click, say)")

	g.domino_close = True


class Opener:
	"""The handler of <button open-window="Settings">."""

	__slots__ = ("name", "__name__")


	def __init__(self, name):

		self.name = name
		self.__name__ = f"open {name}"


	def __call__(self):

		open_window(self.name)


def view(name):
	"""/_domino/window/<Name>: the window as a page, in its layout if it has one."""

	from .components import Document
	from .dtemplates import find_class, in_outer_layouts, layout_values

	try:
		found = definition(name)
	except WindowError:
		abort(404)

	values = {}
	if request.args.get("values"):
		try:
			values = json.loads(request.args["values"])
		except ValueError:
			abort(400)
		if not isinstance(values, dict):
			abort(400)

	cls = find_class(name, found.where, found.where.path)
	element = cls(**{key.replace("-", "_"): value for key, value in values.items()})
	title = found.window.get("title") or name

	if found.outer is not None:
		return in_outer_layouts(element, {"title": title, **layout_values(values)})

	return Document(title=title) [
		element
	]


def add_route(app):

	app.route(ROUTE)(view)


def __getattr__(name):

	# Made on first use: dtemplates imports this module, and MarkupWindow is one of its classes
	if name == "MarkupWindow":
		globals()["MarkupWindow"] = _markup_window()
		return globals()["MarkupWindow"]

	raise AttributeError(name)
