from __future__ import annotations

import os
import re
import secrets
import sys
import threading
import time
import traceback
import uuid
import weakref
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path

import flask
from flask import *
from flask.cli import load_dotenv as load_env_files
from flask.helpers import get_debug_flag, get_load_dotenv
from flask.sessions import SecureCookieSessionInterface
from jinja2 import ChoiceLoader
from markupsafe import Markup, escape
from werkzeug.datastructures import MultiDict

from .settings import Settings, load_settings
from .util import *
from . import css, optimistic, reactive
from .uploads import Uploads


VOID_TAGS = [
	"area", "base", "br", "col", "embed", "hr", "img",
	"input", "link", "meta", "source", "track", "wbr"
]

# Elements whose text content is not HTML and must not be escaped
RAW_TEXT_TAGS = ["script", "style"]

# Elements whose whitespace is content, so rendering adds no indentation inside them
PREFORMATTED_TAGS = ["pre", "textarea"]

# Characters an HTML attribute name can't have (whitespace, quotes, =, /, <, >, controls)
INVALID_ATTRIBUTE_NAME = re.compile(r"[\s\"'<>/=\x00-\x1f\x7f]")

# Attribute names already found valid, so rendering checks each name once
_attribute_names = set()

# What would end a <script> or <style> element early, wherever it is in its text
RAW_TEXT_END = {tag: re.compile(f"</(?={tag})", re.IGNORECASE) for tag in RAW_TEXT_TAGS}


_render_state = threading.local()

# Component class -> its paired Jinja template's path, or None (see domino.templates)
_paired_templates = {}

# Guards Element.__pages__, which request threads add to while refresh() reads it
_pages_lock = threading.Lock()

# The signed-in user's id in Flask's session cookie (see domino.accounts)
SESSION_USER_KEY = "domino_user_id"

# Seconds a browser has to claim a session changed over the WebSocket (see session_handoff)
SESSION_HANDOFF_TTL = 60

# Set in each worker process by `domino serve --workers N` (see domino.workers)
WORKER_ID_ENV = "DOMINO_WORKER_ID"


def max_event_bytes(app):
	"""The largest event (its JSON) the app accepts: DOMINO_MAX_EVENT_MB."""

	return int(float(app.config["DOMINO_MAX_EVENT_MB"]) * 1024 * 1024)


def worker_prefix():
	""""w3-" in worker 3 of `domino serve`, else "". Page ids and session tokens start with it,
	so the router in front of the workers sends their requests to the process that has them."""

	worker = os.environ.get(WORKER_ID_ENV)

	return f"w{worker}-" if worker else ""


def render_stack():
	"""Components whose render() is running in this thread, innermost last."""

	if not hasattr(_render_state, "stack"):
		_render_state.stack = []

	return _render_state.stack


def note_render_error(error, element):
	"""Remember the components a render error passed through, innermost first, for the debug
	error page's component stack (see domino.devtools)."""

	try:
		components = error.__dict__.setdefault("domino_components", [])
	except AttributeError:
		return

	if not any(component is element for component in components):
		components.append(element)


# Component class -> {name: kind} of the props it declares (see component_props)
_component_props = {}

# Settings a component class can have that are never props
NOT_PROPS = ("css", "live", "optimistic", "optimistic_states", "client")


def component_props(cls):
	"""The names a component class declares that keyword arguments set on the component rather
	than as HTML attributes, {name: kind}: "state" (a State attribute: its starting value), "property"
	(one with a setter), "callback" (`on_add = None`: a handler the parent passes, which the component
	calls as self.on_add(...); not a DOM event) and "attribute" (a plain class attribute)."""

	props = _component_props.get(cls)
	if props is not None:
		return props

	props = {}
	for base in reversed(cls.__mro__):
		# Only the app's own components: Domino's classes and tags keep their keyword arguments
		if base.__module__.split(".")[0] == "domino":
			continue
		for name, value in vars(base).items():
			if name.startswith("_") or name in NOT_PROPS:
				continue
			if isinstance(value, reactive.State):
				props[name] = "state"
			elif isinstance(value, property):
				if value.fset is not None:
					props[name] = "property"
			elif name.startswith("on_") and value is None:
				props[name] = "callback"
			elif not callable(value) and not hasattr(type(value), "__get__"):
				props[name] = "attribute"
			else:
				props.pop(name, None)
	_component_props[cls] = props

	return props


def set_prop(element, name, kind, value):

	if kind == "state":
		# Its starting value, without counting as a change
		getattr(type(element), name)._of(element)._value = value
	elif kind == "callback" and callable(value):
		setattr(element, name, Callback(value))
	else:
		setattr(element, name, value)


class Callback:
	"""A handler a parent passed down (TaskForm(on_add=self.add)). The component calls it from its
	own handlers; then the parent is what the event re-renders, unless the event's changes say."""

	__slots__ = ("function",)


	def __init__(self, function):

		self.function = function


	def __call__(self, *args, **kwargs):

		owner = getattr(self.function, "__self__", None)
		if isinstance(owner, Element) and has_request_context() and g.get("domino_page") is not None:
			g.domino_called = owner

		return self.function(*args, **kwargs)


	def __getattr__(self, name):

		return getattr(self.function, name)


	def __repr__(self):

		return f"Callback({self.function!r})"


# CSS of each component class (its own `css`, scoped to its class name), made once
_component_css = {}


def component_css(cls):

	cached = _component_css.get(cls)
	if cached is None:
		cached = css.render(cls.__dict__["css"] or {}, f".{css_class_name(cls)}")
		_component_css[cls] = cached

	return cached


class PageStyles:
	"""The styles one render needs: the CSS of each component class shown, written once,
	and stylesheets computed only when the render is done, so rules added while rendering
	still count. The outermost render (a page, an event response, a push) collects them."""


	def __init__(self):

		self.classes = {}  # CSS class name -> its CSS, in the order first shown
		self.marker = f"<!--domino-styles-{uuid.uuid4().hex}-"
		self.slots = []  # (placeholder, function rendering what replaces it)
		self.placed = False  # whether the component CSS has a place (in the <head>)


	def add(self, cls):

		text = component_css(cls)
		if text:
			self.classes.setdefault(css_class_name(cls), text)


	def slot(self, render):

		placeholder = f"{self.marker}{len(self.slots)}-->"
		self.slots.append((placeholder, render))

		return placeholder


	def place(self, level, indent):
		"""Mark where the component CSS goes (once), and return the mark."""

		if self.placed:
			return ""
		self.placed = True

		# The app's Tailwind CSS, if it uses it, goes first: it's all in cascade layers, so the
		# component CSS and the page's own rules win anyway
		from .tailwind import link

		return self.slot(lambda: link(level, indent) + self.component_style(level, indent))


	def component_style(self, level, indent):

		if not self.classes:
			return ""

		return Element(
			"style",
			inner="\n".join(self.classes.values()),
			data_domino_css=" ".join(self.classes)
		)._render(level, indent)


	def finish(self, html, fallback=True):
		"""Put the styles in their places. Without a <head>, the component CSS goes first
		(unless `fallback` is False: event responses send it separately)."""

		for placeholder, render in self.slots:
			html = html.replace(placeholder, render(), 1)

		if not self.placed and fallback:
			html = self.component_style(0, "") + html

		return html


	def new_for(self, page):
		"""[name, css] for the component classes `page` hasn't been sent yet, now marked sent."""

		new = [[name, text] for name, text in self.classes.items() if name not in page.css]

		# Pages that aren't kept (events bound outside a request) get everything every time
		if page is not DEFAULT_PAGE:
			page.css.update(name for name, _ in new)

		return new


def current_styles():

	return getattr(_render_state, "styles", None)


@contextmanager
def collect_styles():
	"""Collect the styles of everything rendered inside, for PageStyles.finish()."""

	styles = current_styles()
	if styles is not None:
		yield styles
		return

	styles = _render_state.styles = PageStyles()
	try:
		yield styles
	finally:
		_render_state.styles = None


class Page:
	"""Event registry for one rendered page (one page load in one browser tab)."""


	def __init__(self):

		self.id = worker_prefix() + str(uuid.uuid4())
		self.events = {}
		self.lock = threading.RLock()  # serializes events for this page
		self.version = 0  # bumped per update, so the browser can drop stale responses
		self.live = False  # shows a live component, so the browser opens a stream
		self.components = set()  # live components shown here, kept alive as long as the page
		self.updates = {}  # element id -> html not yet sent to the browser
		self.updates_ready = threading.Condition()
		self.stream = None  # the newest stream; older ones stop
		# Who's signed in on this page, from the session when it was made. Pages outlive their
		# request, so events and pushes read this instead of the cookie; reading it subscribes
		self.user_id = reactive.State(None)
		self.css = set()  # components whose CSS the browser has (see PageStyles)
		self.wake = None  # the newest stream's callback for pushes, if it runs in an event loop
		self.cookie = None  # the browser's Cookie header once it had this page, if swapped in by core.js
		self.paused = False  # the tab is hidden, so refresh() leaves this page for resume()
		self.dirty = {}  # components refresh() skipped while paused -> None, in order
		self.hot = None  # what made it, to make it again while hot reloading (see domino.hot)
		self.touch()


	def touch(self):

		self.last_access = time.monotonic()


	def register(self, event_id, element, callback):

		self.events[event_id] = (element, callback)

		# The events a component's render binds, so it can predict its own handlers
		stack = render_stack()
		if stack and event_id.startswith("event-"):
			stack[-1][2].append((event_id, callback))


	def subtree_events(self, root):
		"""This page's events bound to `root` or its descendants."""

		elements = set()
		stack = [root]
		while stack:
			element = stack.pop()
			if isinstance(element, Element) and id(element) not in elements:
				elements.add(id(element))
				stack.extend(element.__children__)
				# Components a Jinja template rendered inline (see domino.templates)
				stack.extend(getattr(element, "__embedded__", ()))

		return {event_id: event for event_id, event in self.events.items() if id(event[0]) in elements}


	def unregister_subtree(self, root):

		# Drop events bound to `root` or its descendants; they are about to be
		# replaced in the browser and would otherwise leak
		for event_id in self.subtree_events(root):
			del self.events[event_id]


	def push(self, element_id, html, css=None):
		"""Queue a re-rendered component for this page's stream. Call with self.lock held."""

		self.version += 1

		with self.updates_ready:
			# A newer render replaces one the browser hasn't received yet; moving
			# it to the end keeps it after any parent re-rendered in between
			previous = self.updates.pop(element_id, None)
			update = {"id": element_id, "html": html, "version": self.version}
			# Component CSS counts as sent once queued, so keep what the replaced update carried
			css = list(css or [])
			if previous and previous.get("css"):
				css = previous["css"] + css
			if css:
				update["css"] = css
			self.updates[element_id] = update
			self.updates_ready.notify_all()
			wake = self.wake

		if wake is not None:
			wake()


	def pause(self):
		"""The tab is hidden: until resume(), refresh() only notes which components changed here."""

		if self is not DEFAULT_PAGE:
			self.paused = True


	def defer(self, component):
		"""Whether this page is paused, in which case `component` is rendered for it on resume()."""

		if not self.paused:
			return False

		with self.lock:
			if not self.paused:
				return False
			self.dirty[component] = None

		return True


	def resume(self):
		"""The tab is shown again: render each component that changed meanwhile, once, and push
		it. Can block (it renders), so not in an event loop."""

		with self.lock:
			if not self.paused:
				return
			self.paused = False
			dirty = list(self.dirty)
			self.dirty.clear()

		for component in dirty:
			component.refresh(only=self)


	def notify(self, message):
		"""Queue a message other than an update for this page's stream, e.g. {"type": "hot"} while
		hot reloading. It's merged into one of its type the browser hasn't received yet."""

		with self.updates_ready:
			key = f"domino:{message['type']}"
			self.updates[key] = dict(self.updates.pop(key, None) or {}, **message)
			self.updates_ready.notify_all()
			wake = self.wake

		if wake is not None:
			wake()


	def open_stream(self, wake=None):
		"""Make a new stream the one that receives pushes. A stream in a thread waits in pull();
		one in an event loop (a WebSocket) passes `wake`, a thread-safe callback run after each
		push, and then takes the updates with pull(stream, 0)."""

		token = object()

		with self.updates_ready:
			replaced = self.wake
			self.stream = token
			self.wake = wake
			self.updates_ready.notify_all()

		# An older socket finds out it was replaced the next time it pulls
		if replaced is not None:
			replaced()

		return token


	def close_stream(self, stream):

		# Updates keep queueing for the next stream, but there's nothing left to wake
		with self.updates_ready:
			if self.stream is stream:
				self.wake = None


	def pull(self, stream, timeout):
		"""Wait up to `timeout` seconds for pushed updates and return them (maybe none),
		or None once a newer stream has replaced `stream`."""

		with self.updates_ready:
			# After a reconnect the old stream may still be waiting here; it must
			# not take updates meant for the new one
			self.updates_ready.wait_for(lambda: self.updates or self.stream is not stream, timeout)
			if self.stream is not stream:
				return None
			updates = list(self.updates.values())
			self.updates.clear()

		return updates


	@staticmethod
	def current():

		# Set by Element.refresh(), which may run outside a request
		page = getattr(_render_state, "page", None)
		if page is not None:
			return page

		if has_app_context() and "domino_page" in g:
			return g.domino_page

		return DEFAULT_PAGE


# Used for events bound outside of a request (e.g. at import time)
DEFAULT_PAGE = Page()


class PageStore:
	"""Where Domino keeps pages between requests.

	Pages hold live Python objects (components and their callbacks), so a store
	must keep them in this process or be able to serialize them. Subclass this
	and pass `Domino(__name__, page_store=...)` to change how pages are kept.
	"""


	def save(self, page):
		raise NotImplementedError


	def load(self, page_id):
		"""Return the page (marking it as used) or None if unknown or expired."""
		raise NotImplementedError


	def delete(self, page_id):
		raise NotImplementedError


	def prune(self, ttl, max_pages):
		"""Drop pages idle for more than `ttl` seconds, then the oldest beyond `max_pages`."""
		raise NotImplementedError


class MemoryPageStore(PageStore):
	"""Keeps pages in this process. With several worker processes, use sticky sessions."""


	def __init__(self):

		# Least recently used first, so pruning only looks at the oldest pages
		self.pages = OrderedDict()
		self.lock = threading.Lock()


	def save(self, page):

		with self.lock:
			self.pages[page.id] = page


	def load(self, page_id):

		with self.lock:
			page = self.pages.get(page_id)
			if page:
				page.touch()
				self.pages.move_to_end(page_id)

		return page


	def delete(self, page_id):

		with self.lock:
			self.pages.pop(page_id, None)


	def prune(self, ttl, max_pages):

		with self.lock:
			while len(self.pages) > max_pages:
				self.pages.popitem(last=False)

			# Stop at the first page still in use; everything after it is newer
			cutoff = time.monotonic() - ttl
			while self.pages:
				oldest = next(iter(self.pages.values()))
				if oldest.last_access >= cutoff:
					break
				self.pages.popitem(last=False)


class Event:
	"""What the browser sent with an event: the element's value, its form's fields, and the
	files it uploaded (a MultiDict of UploadedFile: `files["photo"]`, `files.getlist("photos")`)."""


	def __init__(self, type, value=None, form=None, files=None):

		self.type = type
		self.value = value
		self.form = form or {}
		self.files = files if files is not None else MultiDict()


	@staticmethod
	def from_request(event_id, data, files=None):

		if not isinstance(data, dict):
			data = {}

		form = data.get("form")
		if not isinstance(form, dict):
			form = {}

		# A form's fields are strings (lists of them for repeated names), as core.js sends them.
		# Anything else (a dict like {"$ne": null}) would turn a MongoDB query made from a field,
		# users.find_one({"email": event.form["email"]}), into another query
		form = {name: value for name, value in ((name, form_value(value)) for name, value in form.items()) if value is not None}

		type_ = "after" if event_id.startswith("after-") else event_id.rsplit("-", 1)[-1]

		return Event(type_, data.get("value"), form, files)


	def __repr__(self):

		return f"Event(type={self.type!r}, value={self.value!r}, form={self.form!r})"


def form_value(value):
	"""A form field sent by the browser as a string or a list of strings, or None for other values."""

	if isinstance(value, str):
		return value

	if isinstance(value, list):
		return [item for item in value if isinstance(item, str)]

	return None


def redirect(location, code=302):
	"""Send the browser to `location`. In an event handler the browser goes there once the
	response arrives, and `location` must be a path on this site; elsewhere (e.g. in a route)
	this is Flask's redirect()."""

	if not (has_request_context() and "domino_redirect" in g):
		return flask.redirect(location, code)

	# Event handlers often pass on a ?next= from the query string, so refuse other sites
	if not is_local_url(location):
		raise ValueError(f"Can only redirect to a path on this site, not {location!r}")

	g.domino_redirect = location


class SessionInterface(SecureCookieSessionInterface):
	"""Flask's signed cookie session, with SameSite=Lax and Secure outside debug by default."""


	def should_set_cookie(self, app, session):

		# The session hand-off sets the cookie it was given; refreshing the request's own
		# session after it would undo a logout
		if g.get("domino_session_handoff"):
			return False

		return super().should_set_cookie(app, session)


	def get_cookie_samesite(self, app):

		return app.config["SESSION_COOKIE_SAMESITE"] or "Lax"


	def get_cookie_secure(self, app):

		# The debug server is usually plain http://127.0.0.1; {"domino": {"secure_cookies": false}}
		# turns this off for an HTTP-only deployment
		secure = app.config.get("DOMINO_SECURE_COOKIES")
		if secure is None:
			return app.config["SESSION_COOKIE_SECURE"] or not app.debug

		return bool(secure)


class Domino(Flask):

	session_interface = SessionInterface()


	def __init__(self, *args, page_store: PageStore = None, settings: str = None, pages=None, **kwargs):

		# URL rule -> the file in pages/ serving it. Set first: Flask.__init__ adds a route
		self._page_rules = {}
		self._page_routes = {}  # URL rule (None for 404.py) -> its domino.pages.PageRoute

		super().__init__(*args, **kwargs)

		self.config.setdefault("DOMINO_PAGE_TTL", 30 * 60)  # seconds of inactivity
		self.config.setdefault("DOMINO_MAX_PAGES", 1000)
		self.config.setdefault("DOMINO_KEEPALIVE", 15)  # seconds between stream keepalives
		self.config.setdefault("DOMINO_WEBSOCKET", True)  # one WebSocket per tab when served over ASGI
		self.config.setdefault("DOMINO_WORKERS", 32)  # threads for event handlers (and for requests) over ASGI
		self.config.setdefault("DOMINO_NAVIGATION", True)  # links to other pages swap them in without reloading
		self.config.setdefault("DOMINO_MAX_UPLOAD_MB", 16)  # per upload request (all its files)
		self.config.setdefault("DOMINO_MAX_PENDING_UPLOADS_MB", 256)  # uploads waiting for their event, all pages together
		self.config.setdefault("DOMINO_UPLOAD_TTL", 10 * 60)  # seconds an upload waits for its event
		self.config.setdefault("DOMINO_MAX_EVENT_MB", 1)  # per event sent (its JSON), over HTTP or the WebSocket
		self.config.setdefault("DOMINO_FRAME_OPTIONS", "SAMEORIGIN")  # X-Frame-Options; False lets other sites frame pages
		self.config.setdefault("DOMINO_PATCHES", True)  # the WebSocket sends what changed in a component, not all of it
		self.config.setdefault("DOMINO_WS_COMPRESSION", True)  # per-message deflate on the WebSocket (uvicorn's)
		self.config.setdefault("DOMINO_HOT_RELOAD", True)  # debug mode updates pages in place on changes
		self.config.setdefault("DOMINO_CLIENT_RUNTIME", None)  # client components' runtime: a URL, "local" or "cdn"
		self.config.setdefault("DOMINO_CLIENT_PYTHON", "micropython")  # or "pyodide"

		# settings.json < settings.local.json < DOMINO_* environment variables
		self.settings = load_settings(self.root_path, settings)
		self._apply_settings()

		# Named Collections find MongoDB through these settings (mongo.url)
		from . import mongo
		mongo.use_app(self)

		self.page_store = page_store or MemoryPageStore()
		self._asgi = None
		self.hot_reloader = None  # updates open pages when files change, while debugging (see domino.hot)

		# .html templates anywhere in the app's folder, found by file name (see domino.templates)
		from .templates import TemplateFinder
		self.template_finder = TemplateFinder(
			self.root_path, self.template_folder,
			pages=None if pages is False else (pages or "pages"), setting=self.settings.get("templates")
		)

		with open(Path(__file__).parent / 'core.js', encoding='utf-8') as js_file:
			CORE_JS = js_file.read()

		self._add_static_route('/_domino/core', CORE_JS)
		self._add_event_handler('/_domino/events')
		self._add_upload_handler('/_domino/upload')
		self._add_stream('/_domino/stream')
		self._add_oauth_routes('/_domino/accounts/<provider>/<action>')
		self._add_session_handoff('/_domino/session/<token>')
		self._add_health_check('/_domino/health')

		# The inspector's script and data; they answer 404 unless the app is in debug mode
		from .devtools import add_routes
		add_routes(self)

		# Client components' loader, modules and runtime (see domino.client)
		from . import client
		client.add_routes(self)

		# {"tailwind": true} or a tailwind.css in the app's folder: every page links its CSS
		from . import tailwind
		self.tailwind = tailwind.options(self.settings, self.root_path)
		if self.tailwind:
			tailwind.add_routes(self)

		# File-based routing, found once here rather than per request
		self._add_pages(pages)


	def _add_pages(self, pages):

		from .pages import PagesError, add_pages

		# pages=None uses the app's pages/ folder if there is one; False turns pages off
		if pages is False:
			return

		folder = Path(self.root_path) / (pages or "pages")
		if not folder.is_dir():
			if pages:
				raise PagesError(f"No pages folder at {folder}")
			return

		add_pages(self, folder)


	def add_url_rule(self, rule, endpoint=None, view_func=None, **options):

		# Two handlers for one URL is a mistake, and Flask would quietly use the first
		page = self._page_rules.get(rule)
		if page:
			from .pages import PagesError
			name = endpoint or getattr(view_func, "__name__", view_func)
			raise PagesError(f'Two handlers for "{rule}": {page} and the route "{name}"')

		return super().add_url_rule(rule, endpoint, view_func, **options)


	def create_global_jinja_loader(self):

		return ChoiceLoader([super().create_global_jinja_loader(), self.template_finder])


	def create_jinja_environment(self):

		from .templates import component, on

		environment = super().create_jinja_environment()
		environment.globals.update(component=component, on=on)

		return environment


	def _apply_settings(self):

		# {"domino": {"page_ttl": 600}} -> DOMINO_PAGE_TTL; changes made in code later still win
		for key, value in (self.settings.get("domino") or {}).items():
			self.config[f"DOMINO_{key.upper()}"] = value

		if self.settings.get("secret_key"):
			self.secret_key = self.settings["secret_key"]


	def test_page(self, path="/", client=None):
		"""Load `path` in a simulated browser, to click, type and check it in tests."""

		from .testing import TestPage

		return TestPage(self, path, client)


	def run(self, host=None, port=None, debug=None, load_dotenv=True, **options):

		# Like `meteor run`: in debug mode an app without a mongo.url setting gets a local
		# MongoDB, started once in the parent process (the reloader's child inherits the URL).
		# .env may set FLASK_DEBUG, so it's read first, as Flask does
		if get_load_dotenv(load_dotenv):
			load_env_files()

		if debug is not None:
			debug_mode = bool(debug)
		elif "FLASK_DEBUG" in os.environ:
			debug_mode = get_debug_flag()
		else:
			debug_mode = self.debug

		in_child = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
		from_flask_cli = os.environ.get("FLASK_RUN_FROM_CLI") == "true"

		if debug_mode and not in_child and not from_flask_cli:
			self._start_dev_mongo(port or 5000)

		# Tailwind's CSS too: rebuilt as files change while debugging, built once in production
		if self.tailwind and not in_child and not from_flask_cli:
			from . import tailwind
			if debug_mode:
				tailwind.watch(self.root_path, self.tailwind)
			else:
				tailwind.prepare(self.root_path, self.tailwind)

		# `flask run` serves the app itself, and Flask's run() knows to do nothing then
		if from_flask_cli:
			return super().run(host=host, port=port, debug=debug, load_dotenv=load_dotenv, **options)

		# Served with uvicorn, so pages get the WebSocket; in debug mode it restarts on changes
		self.debug = debug_mode
		reload = options.pop("use_reloader", debug_mode)
		options.pop("threaded", None)  # Werkzeug's; uvicorn needs no thread per request

		from .asgi import app_location, serve

		# Like `domino serve --workers N`: processes that each load the app from its file
		workers = options.pop("workers", None) or 1
		if workers > 1 and reload:
			self.logger.warning("Domino: serving one process, not %s workers, while reloading on changes", workers)
		elif workers > 1 and app_location(self) is None:
			self.logger.warning("Domino: serving one process; for workers the app must be defined at the top level of a module file")
		elif workers > 1:
			from . import workers as serving
			serving.serve(app_location(self), host or "127.0.0.1", port or 5000, workers)
			return

		# Port 0 picks a free port
		serve(self, host or "127.0.0.1", 5000 if port is None else port, reload, **options)


	@property
	def asgi(self):
		"""This app as an ASGI application, for uvicorn: `uvicorn myapp:app.asgi`."""

		if self._asgi is None:
			from .asgi import ASGIApp
			self._asgi = ASGIApp(self)

		return self._asgi


	def _start_dev_mongo(self, app_port):

		from . import devmongo

		reason = devmongo.disabled_reason(self.settings)
		if reason == "settings mongo.url":
			devmongo.log("MongoDB: settings mongo.url")
			return
		if reason:
			devmongo.log("MongoDB: disabled")
			return

		mongo = self.settings.get("mongo")
		if not isinstance(mongo, dict):
			mongo = self.settings["mongo"] = Settings()

		version = str(mongo.get("version") or devmongo.DEFAULT_VERSION)
		url = devmongo.start(self.root_path, devmongo.mongod_port(app_port), version)

		os.environ["DOMINO_MONGO__URL"] = url
		mongo["url"] = url
		devmongo.log(f"MongoDB: {url}")


	def _add_event_handler(self, route):

		def event_handler():

			# Only JSON: a cross-site form can't send it, and a cross-site fetch can't
			# without a CORS preflight, which is never granted. That makes this CSRF-safe
			if not request.is_json:
				return jsonify({"error": "Expected application/json"}), 415

			# Read at most DOMINO_MAX_EVENT_MB, so a huge body can't take the server's memory
			limit = max_event_bytes(self)
			if (request.content_length or 0) > limit:
				return jsonify({"error": "Event too large"}), 413
			body = request.stream.read(limit + 1)
			if len(body) > limit:
				return jsonify({"error": "Event too large"}), 413

			# Retrieve the event data from the incoming JSON payload
			try:
				data = json.loads(body) if body else {}
			except (ValueError, RecursionError):
				data = {}
			if not isinstance(data, dict):
				data = {}

			# Access the page_id and event_id sent by the client-side JavaScript
			page = self._get_page(data.get("page_id")) or DEFAULT_PAGE

			payload, status = self.handle_event(page, data.get("event_id"), data.get("data"))

			return jsonify(payload), status

		self.add_url_rule(route, route, event_handler, methods=["POST"])


	def _add_upload_handler(self, route):

		from werkzeug.exceptions import RequestEntityTooLarge
		from .uploads import parse

		self.uploads = Uploads(self.config)

		def upload_handler():

			# A cross-site form can post multipart, but can't add a header (and a cross-site
			# fetch with one needs a CORS preflight, never granted), so this is CSRF-safe
			page_id = request.headers.get("X-Domino-Page")
			if not page_id:
				return jsonify({"error": "Expected an X-Domino-Page header"}), 403

			page = self._get_page(page_id)
			if page is None:
				return jsonify({"error": "Unknown or expired page"}), 404

			limit = self.config["DOMINO_MAX_UPLOAD_MB"]
			too_large = {"error": f"Upload too large: the limit is {limit:g} MB"}
			if self.debug or self.testing:
				too_large["debug"] = True  # for the browser's error overlay
			# Refused before reading the body when its size is known; parse() checks as it reads
			max_bytes = int(limit * 1024 * 1024)
			if (request.content_length or 0) > max_bytes:
				return jsonify(too_large), 413
			try:
				files = parse(request.environ, max_bytes)
			except RequestEntityTooLarge:
				return jsonify(too_large), 413

			return jsonify({"files": self.uploads.add(page.id, files)})

		self.add_url_rule(route, route, upload_handler, methods=["POST"])


	def _event_response(self, response):

		if g.get("domino_redirect"):
			response["redirect"] = g.domino_redirect

		# For the inspector's event log (see handle_event)
		debug = g.get("domino_debug")
		if debug:
			from .devtools import describe_callback
			response["debug_ms"] = round((time.perf_counter() - debug[0]) * 1000, 1)
			response["debug_handler"] = describe_callback(debug[1])

		return response


	def handle_event(self, page, event_id, data):
		"""Run an event's callback and render what it changed. Returns (payload, status) for the
		browser, the same over every transport (HTTP POST or WebSocket). Call it in a request
		context. It can block, so the WebSocket runs it in a worker thread."""

		# A page acts as the user signed in when it was made, so its id alone mustn't be enough to
		# act as them: the browser must still be signed in as that user (one signed out since, in
		# another tab, say, reloads the page)
		owner = page.user_id._value
		if owner is not None and has_request_context() and session.get(SESSION_USER_KEY) != owner:
			return {"error": "Unknown or expired page"}, 404

		# Reactive changes the callback makes re-render their subscribers once the page
		# lock is released (updating other pages while holding it could deadlock)
		# Files the event uploaded first, by token; deleted once it's handled
		with reactive.batch(background=True) as changes, page.lock, self.uploads.claim(page, data) as files:

			event = None
			if isinstance(event_id, str):
				event = page.events.get(event_id) or DEFAULT_PAGE.events.get(event_id)
			if event is None:
				return {"error": "Unknown or expired event"}, 404
			if files is None:
				return {"error": "Unknown or expired upload"}, 400

			g.domino_page = page
			g.domino_redirect = None  # set by redirect()
			g.domino_called = None  # a parent whose handler the callback called (see Callback)

			_, callback = event

			# Only while debugging: the handler and the time it took, for the inspector's event log
			if self.debug:
				g.domino_debug = (time.perf_counter(), callback)

			try:
				if accepts_argument(callback):
					result = callback(Event.from_request(event_id, data, files))
				else:
					result = callback()

				# A handler that returns nothing re-renders the component its changes
				# affected on this page, or else the parent whose handler it called, or else the
				# component it's a method of
				if result is None:
					result = changes.affected_on(page) or g.domino_called or getattr(callback, "__self__", None)

				if not isinstance(result, Element):
					return self._event_response({"id": None, "html": None}), 200

				# Old binds must go before rendering so the new ones register fresh.
				# If rendering fails the browser still shows the old HTML, so put
				# the old events back and drop any the failed render added
				events = dict(page.events)
				page.unregister_subtree(result)
				try:
					with collect_styles() as styles:
						html = result._render()
				except Exception:
					page.events.clear()
					page.events.update(events)
					raise
			except Exception as error:
				return self._event_error(event_id, error)

			page.version += 1

			# The response carries this render, so it isn't pushed to this page again
			changes.skip(page, result)

			response = {
				"id": result.id(),
				"html": styles.finish(html, fallback=False),
				"version": page.version
			}

			# CSS of components this page hasn't shown before; core.js adds it to the head
			css = styles.new_for(page)
			if css:
				response["css"] = css

			return self._event_response(response), 200


	def _event_error(self, event_id, error):

		self.logger.exception("Domino event %s failed", event_id)

		# Tracebacks can reveal code and data, so only send them while debugging or testing
		if not (self.debug or self.testing):
			return {"error": "Internal Server Error"}, 500

		payload = {
			"error": f"{type(error).__name__}: {error}",
			"traceback": traceback.format_exc(),
			"debug": True
		}

		# The frames with their source, the component stack and hints, for debug.js's overlay
		if self.debug:
			from .devtools import error_details
			debug = g.get("domino_debug")
			payload.update(error_details(self, error, debug[1] if debug else None))
			if debug:
				payload["debug_ms"] = round((time.perf_counter() - debug[0]) * 1000, 1)

		return payload, 500


	def _add_stream(self, route):

		def stream():

			page = self._get_page(request.args.get("page"))
			if page is None:
				return jsonify({"error": "Unknown or expired page"}), 404

			stream = page.open_stream()

			def updates():

				# Runs after the request has returned, so don't touch request or g.
				# When the client goes away, the next yield raises GeneratorExit
				# Servers send the headers with the first chunk, so send one now
				yield ": open\n\n"
				while True:
					pushed = page.pull(stream, self.config["DOMINO_KEEPALIVE"])
					if pushed is None:
						return
					# Loading touches the page, so an open stream keeps it alive; stop
					# if it's gone anyway (expired, or pushed out by DOMINO_MAX_PAGES)
					if self._get_page(page.id) is None:
						return
					for update in pushed:
						yield f"data: {json.dumps(update)}\n\n"
					if not pushed:
						yield ": keepalive\n\n"

			return Response(updates(), mimetype="text/event-stream", headers={
				"Cache-Control": "no-cache",
				"X-Accel-Buffering": "no"
			})

		self.add_url_rule(route, route, stream, methods=["GET"])


	def session_handoff(self, session, page=None):
		"""For events that ran over the WebSocket, which can't set cookies: the Set-Cookie headers
		for a session the handler changed, kept under a one-time token (or None if unchanged).
		The browser POSTs the token to /_domino/session/<token> to get the cookie, naming `page`
		(the page the event ran on) in an X-Domino-Page header."""

		if not session.modified:
			return None, []

		response = self.response_class()
		self.session_interface.save_session(self, session, response)
		cookies = response.headers.getlist("Set-Cookie")
		if not cookies:
			return None, []

		token = worker_prefix() + secrets.token_urlsafe(32)
		now = time.monotonic()
		with self._handoffs_lock:
			# Unclaimed tokens (the tab closed) expire after a minute
			for old, (created, _, _) in list(self._handoffs.items()):
				if now - created > SESSION_HANDOFF_TTL:
					del self._handoffs[old]
			page_id = page.id if page is not None and page is not DEFAULT_PAGE else None
			self._handoffs[token] = (now, cookies, page_id)

		return token, cookies


	def _add_session_handoff(self, route):

		self._handoffs = {}
		self._handoffs_lock = threading.Lock()

		def handoff(token):

			# Like uploads: a cross-site form can POST here but can't add a header, so another
			# site can't plant a session it got a token for (its own login) in a visitor's browser
			page_id = request.headers.get("X-Domino-Page")
			if not page_id:
				return jsonify({"error": "Expected an X-Domino-Page header"}), 403

			with self._handoffs_lock:
				created, cookies, owner = self._handoffs.get(token, (None, None, None))
				# Only for the page whose event changed the session
				if cookies is not None and owner is not None and owner != page_id:
					return jsonify({"error": "This session token is for another page"}), 403
				self._handoffs.pop(token, None)

			if cookies is None or time.monotonic() - created > SESSION_HANDOFF_TTL:
				return jsonify({"error": "Unknown or expired session token"}), 404

			g.domino_session_handoff = True
			response = self.response_class(status=204)
			for cookie in cookies:
				response.headers.add("Set-Cookie", cookie)
			response.headers["Cache-Control"] = "no-store"

			return response

		self.add_url_rule(route, "domino_session", handoff, methods=["POST"])


	def _add_oauth_routes(self, route):

		def oauth(provider, action):

			# Imported here so apps without accounts don't load it
			from . import accounts

			return accounts.oauth_view(provider, action)

		self.add_url_rule(route, "domino_oauth", oauth, methods=["GET"])


	def _new_page(self):

		page = Page()
		page.user_id.set(session.get(SESSION_USER_KEY))
		page.app = self  # for rendering Jinja templates outside a request, e.g. in refresh()

		self.page_store.save(page)
		self._prune_pages()

		g.domino_page = page

		return page


	def _get_page(self, page_id):

		self._prune_pages()

		# Ids come from the browser, which may send anything
		return self.page_store.load(page_id) if page_id and isinstance(page_id, str) else None


	def _drop_page(self, page):

		self.page_store.delete(page.id)


	def _prune_pages(self):

		self.page_store.prune(self.config["DOMINO_PAGE_TTL"], self.config["DOMINO_MAX_PAGES"])


	def _add_health_check(self, route):

		# For load balancers and container platforms to check the app answers: no page is made
		def health():
			return Response("ok", mimetype="text/plain", headers={"Cache-Control": "no-store"})

		self.add_url_rule(route, "domino_health", health, methods=["GET"])


	def _add_static_route(self, route, data):

		self.add_url_rule(route, route, lambda: Response(data, mimetype="text/javascript"), methods=["GET"])


	def route(self, rule, **options):

		# Get the original route decorator
		flask_decorator = super().route(rule, **options)

		def decorator(function):

			# Define a new wrapper function
			def wrapper(*args, **kwargs):

				return self._render_view(function, *args, **kwargs)
			
			# Set a unique name for the wrapper function
			wrapper.__name__ = function.__name__

			# Apply the Flask route decorator to the wrapper
			return flask_decorator(wrapper)

		return decorator


	def _render_view(self, function, *args, **kwargs):
		"""Call a view (a route or a file in pages/) and render the component it returns."""

		# core.js is swapping this page in for the one it names, and has no WebSocket to say it's
		# leaving that one (see navigate() in core.js), so drop it now
		leaving = request.headers.get("X-Domino-Leave")
		if leaving:
			self.page_store.delete(leaving)

		# Events bound while building and rendering this response belong to a new page
		page = self._new_page()

		# Call the original handler function
		result = function(*args, **kwargs)

		# Check if the result has a `render` method
		if hasattr(result, "_render"):
			result.configure(data_domino_page=page.id)
			# Only while debugging, so the latency setting can't slow down production
			if self.debug and self.config.get("DOMINO_LATENCY"):
				result.configure(data_domino_latency=int(self.config["DOMINO_LATENCY"]))
			# Served through app.asgi, so the browser can open a WebSocket instead of POST + SSE
			if request.environ.get("domino.websocket"):
				result.configure(data_domino_ws=True)
			# Links then load pages from scratch, as without core.js
			if not self.config["DOMINO_NAVIGATION"]:
				result.configure(data_domino_reload=True)
			# Updated in place when files change, so it's kept even with nothing to handle
			if self.hot_reloader is not None:
				result.configure(data_domino_hot=True)
				self.hot_reloader.remember(page, result, function, args, kwargs)
			with collect_styles() as styles:
				html = result._render()
			html = styles.finish(html)
			# The page's <head> has their CSS, so event responses needn't send it
			page.css.update(styles.classes)
		else:
			html = result

		# While debugging, the inspector finds the page's components from its root, and can
		# inspect pages without events too
		if self.debug:
			page.root = result
		# Don't keep pages that have nothing to handle or refresh
		elif not page.events and not page.live and page.hot is None:
			self._drop_page(page)

		return html


	def process_response(self, response):

		response = super().process_response(response)

		# A page core.js swaps in keeps the tab's WebSocket, whose handshake sent older cookies;
		# remember the ones the browser has now (the session is saved by this point), for the
		# socket's events on this page
		page = g.get("domino_page")
		if page is not None and request.headers.get("X-Domino-Navigate") and request.environ.get("domino.websocket"):
			from .asgi import with_cookies
			page.cookie = with_cookies(request.headers.get("Cookie", ""), response.headers.getlist("Set-Cookie"))

		# Another site can't show the app's pages in a frame and trick visitors into clicking its
		# buttons (clickjacking); {"domino": {"frame_options": false}} allows it. Responses keep
		# their declared type, and links to other sites don't send the page's query (tokens)
		frame_options = self.config.get("DOMINO_FRAME_OPTIONS", "SAMEORIGIN")
		if frame_options:
			response.headers.setdefault("X-Frame-Options", str(frame_options))
		response.headers.setdefault("X-Content-Type-Options", "nosniff")
		response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")

		return response


	def handle_exception(self, e):

		# While debugging, a page that fails shows what went wrong (the frames with their source,
		# the component whose render() failed, hints) instead of a bare 500. Not in tests, which
		# want the exception, nor under Werkzeug's interactive debugger, which shows its own
		if not self.debug or self.testing or request.environ.get("werkzeug.debug.preserve_context"):
			return super().handle_exception(e)

		from .devtools import error_page

		self.log_exception(sys.exc_info())
		response = self.response_class(error_page(self, e), status=500, mimetype="text/html")

		return self.finalize_request(response, from_error_handler=True)


	def style(self, href="", external=False):

		self.stylesheet = Style(self, href, external)

		return self.stylesheet


class Element:


	def __init__(self, tag=None, parent=None, inner=None, void=None, **kwargs):

		# print(f"Initializing {self} within {parent}")

		self.__children__ = []
		self.__parent__ = None
		self.__tag__ = ""
		self.__inner__ = ""
		self.__void__ = None
		self.__attributes__ = {}
		self.__states__ = {}
		self.__styles__ = {}
		self.__id__ = None  # a random id, made only if something asks for it
		self.__id_used__ = False
		self.__pages__ = None  # live pages this component was rendered on (components only)
		self.__dependencies__ = set()  # reactive data its last render read

		self.tag(tag)
		self.parent(parent)
		self.inner(inner)
		self.void(void)
		self.configure(**kwargs)

		self.content_root: Element = self

		if hasattr(self, 'init'):
			self.init()


	def __init_subclass__(cls, **kwargs):

		super().__init_subclass__(**kwargs)

		# `client = True` runs the component in the browser; its module is checked now, so a
		# mistake stops the app at startup (see domino.client)
		if getattr(cls, "client", False) is True:
			from . import client
			client.register(cls)


	def add_children(self, children: list[Element | str]):
		self.content_root.__children__.extend(children)
		return self


	def set_children(self, children: list[Element | str]):
		self.content_root.__children__ = children
		return self


	def __getitem__(self, children):
		if isinstance(children, tuple):
			children = list(children)
		else:
			children = [children]
		return self.set_children(children)
	

	def __call__(self, children: list[Element | str]):
		return self.set_children(children)


	def __str__(self):
		return self._render()


	def __html__(self):

		# Jinja calls this for {{ element }}; inside a component's render, remember the
		# element so the component's re-render replaces its events too
		stack = render_stack()
		if stack:
			stack[-1][0].__embedded__.append(self)

		return self._render()
	

	def __len__(self):
		return len(self.content_root.__children__)


	def parent(self, parent=None):
		if parent is None:
			return self.__parent__
		if self.__parent__:
			self.__parent__.__children__.remove(self)
		self.__parent__ = parent
		if self not in self.__parent__.__children__:
			self.__parent__.__children__.append(self)
		return self


	def tag(self, tag=None):
		if tag is None:
			return self.__tag__
		self.__tag__ = tag
		return self


	def inner(self, inner=None):
		if inner is None:
			return self.__inner__
		self.__inner__ = inner
		return self
	

	def void(self, void=None):
		if void is None:
			return self.__void__
		self.__void__ = void
		return self


	def id(self, id_=None):
		if id_ is None:
			# Anything that asks for the id may rely on it being in the page
			self.__id_used__ = True
			if self.__attributes__.get('id'):
				return str(self.__attributes__['id'])
			if self.__id__ is None:
				self.__id__ = uuid.uuid4()
			return str(self.__id__)
		self.__attributes__['id'] = id_
		return self


	def configure(self, **kwargs):

		# Names the component declares (State, a property, `on_add = None`, a class attribute) are
		# its props: a parent passes data and its own handlers down with them (see component_props)
		props = component_props(type(self))
		if props:
			for key in [key for key in kwargs if key in props]:
				set_prop(self, key, props[key], kwargs.pop(key))

		# on_click=handler binds the event like bind("click", handler); debounce= applies to them
		handlers = [key for key in kwargs if key.startswith("on_") and callable(kwargs[key])]
		debounce = None
		if handlers:
			debounce = kwargs.pop("debounce", None)
		for key in handlers:
			self.bind(key[3:], kwargs.pop(key), debounce=debounce)

		self.__attributes__.update(kwargs)
		return self


	def _event_id(self, kind, suffix):

		# Inside a component's render(), number events per component so the
		# same button gets the same event id every time it's re-rendered;
		# clicks sent from the previous render then still find their handler
		stack = render_stack()
		if stack:
			frame = stack[-1]
			frame[1] += 1
			return f"{kind}-{frame[0].id()}-{frame[1]}-{suffix}"

		return f"{kind}-{self.id()}-{suffix}"


	def bind(self, event, callback, debounce=None):

		event = event.lower()
		event_id = self._event_id("event", event)

		# An element can have several events, kept as a space-separated list
		event_ids = (self.__attributes__.get("data_event_id") or "").split()
		if event_id not in event_ids:
			event_ids.append(event_id)
		self.configure(data_event_id=" ".join(event_ids))

		# Wait until the user pauses for `debounce` ms before sending (e.g. typing)
		if debounce:
			self.configure(**{f"data_debounce_{event}": int(debounce)})

		Page.current().register(event_id, self, callback)

		return self


	def after(self, delay: int, func):

		event_id = self._event_id("after", delay)

		self.configure(data_after_id=event_id)
		Page.current().register(event_id, self, func)

		return self


	def _predict(self, page, indent, bound):
		"""The states this component's predictable handlers lead to, each rendered once, and
		which event leads where (see domino.optimistic.graph), or None. `bound` are the events
		its real render() just bound. Rendering the predictions changes nothing the real render
		made: its children, the events it bound, its subscriptions."""

		cls = type(self)
		if getattr(cls, "optimistic", True) is False:
			return None
		callbacks = optimistic.own_callbacks(self, bound)
		if not callbacks:
			return None

		children = self.__children__
		content = self.content_root.__children__
		embedded = self.__embedded__
		events = dict(page.events)
		# A Domino template sets attributes of the component's element as it renders (see
		# dtemplates._root); the real render's stay
		attributes = dict(self.__attributes__)
		root = self.__dict__.get("_domino_root")

		def render(overlay):
			with reactive.predicting(overlay):
				# Same formatting as the real render, so the browser patches the component
				# in place instead of rebuilding it
				html = self._render(indent=indent)
			return html, self.__bound__

		try:
			return optimistic.graph(self, callbacks, render, getattr(cls, "optimistic_states", None))
		finally:
			self.__children__ = children
			self.content_root.__children__ = content
			self.__embedded__ = embedded
			self.__attributes__ = attributes
			if root is not None:
				self.__dict__["_domino_root"] = root
			page.events.clear()
			page.events.update(events)


	def is_live(self):
		"""Whether pages showing this component need a stream for refresh()."""

		return getattr(type(self), "live", False) is True or bool(self.__dependencies__)


	def refresh(self, skip=None, only=None):
		"""Re-render this component and push it to every live page showing it (except `skip`;
		or just to `only`)."""

		with _pages_lock:
			pages = [page for page in self.__pages__ or () if page is not skip and (only is None or page is only)]

		# Hidden tabs get it once they're shown again, rendered once however often it changed
		pages = [page for page in pages if not page.defer(self)]

		if not pages:
			return self

		# Render once, on the first page, then share the HTML and the events it bound
		first = pages[0]
		with first.lock:
			# Like the event handler: binds made while rendering belong to this page
			previous = getattr(_render_state, "page", None)
			_render_state.page = first
			try:
				first.unregister_subtree(self)
				with collect_styles() as styles:
					html = self._render()
			finally:
				_render_state.page = previous
			html = styles.finish(html, fallback=False)
			events = first.subtree_events(self)
			first.push(self.id(), html, styles.new_for(first))

		for page in pages[1:]:
			with page.lock:
				page.unregister_subtree(self)
				page.events.update(events)
				page.push(self.id(), html, styles.new_for(page))

		return self


	def _paired_render(self):

		cls = type(self)
		path = _paired_templates.get(cls, False)
		if path is False:
			from .templates import paired_template
			path = paired_template(cls)
			_paired_templates[cls] = path
		if path is None:
			return None

		from .templates import render_paired

		return lambda: render_paired(self, path)


	def _render(self, level=0, indent=4) -> str:

		# The outermost render collects the styles of everything in it and puts them in
		# place at the end. Element._render, not self._render: subclasses call this from theirs
		styles = current_styles()
		if styles is None:
			with collect_styles() as styles:
				html = Element._render(self, level, indent)
			return styles.finish(html)

		# Rendered by the code the browser will run it with (see domino.client)
		if getattr(type(self), "client", False) is True:
			from . import client
			return client.render(self, level, indent, styles)

		# A component without render() may have a paired Jinja template instead
		render = getattr(self, "render", None)
		if render is None:
			render = self._paired_render()

		if render is not None:
			# Remember where this component is shown so refresh() can update it there
			page = Page.current()
			if page is not DEFAULT_PAGE:
				with _pages_lock:
					if self.__pages__ is None:
						self.__pages__ = weakref.WeakSet()
					self.__pages__.add(page)

			# Subscriptions are rebuilt by whatever this render reads (a prediction's reads
			# subscribe nothing, so the real render's stay)
			predicting = reactive.is_predicting()
			if not predicting:
				reactive.forget(self)
			self.__embedded__ = []
			# [component, events numbered so far, (event id, callback) bound by its render]
			frame = [self, 0, []]
			render_stack().append(frame)
			try:
				children = render()
			except Exception as error:
				note_render_error(error, self)
				raise
			finally:
				render_stack().pop()
			self.__bound__ = frame[2]

			# render() may return its children instead of calling self([...])
			if children is not None and children is not self:
				if not isinstance(children, (list, tuple)):
					children = [children]
				self.set_children(list(children))

			if page is not DEFAULT_PAGE and self.is_live():
				page.live = True
				page.components.add(self)

			predictions = None
			if page is not DEFAULT_PAGE and not predicting:
				predictions = self._predict(page, indent, frame[2])
		else:
			predictions = None

		# Handle the case where indent is an integer
		if isinstance(indent, int):
			indent = " " * indent  # Convert to spaces

		# If the indent is a string (e.g., "\t"), it will be used directly
		tag = self.__tag__
		inner = self.__inner__
		void = self.__void__

		if inner is None:
			inner = ""

		# Calculate the indentation for this level
		indentation = indent * level
		end = "" if indent == "" else "\n"

		# Styles set on this element with Style.style(element, ...)
		def element_style(style_level):
			if not self.__styles__:
				return ""
			rules = Style.css({Style.id_selector(self.id()): self.__styles__})
			return Element("style", inner=rules)._render(style_level, indent)

		html = f"{indentation}<{tag}"

		# Handle class names: every class in the hierarchy except the tag itself,
		# so mixins and parent components (e.g. col_6 -> col-6) are kept
		class_names = []
		styled = []
		for base in self.__class__.__mro__:
			if base in (object, Element) or base.__name__ == tag or base.__module__ == "domino.tags":
				continue
			name = css_class_name(base)
			if name not in class_names:
				class_names.append(name)
			if "css" in base.__dict__:
				styled.append(base)
		is_component = len(class_names) > 0

		# Class-level `css`, written once per page; base classes first so subclasses override
		for base in reversed(styled):
			styles.add(base)

		# Add attributes
		attributes = get_class_attributes(self)
		if "class" in attributes:
			attributes.pop("class")
		attributes.pop("css", None)
		# A prop the parent passed (see component_props) shows its value, not the class's; a list,
		# dict or object isn't an HTML attribute
		for key, value in list(attributes.items()):
			value = self.__dict__.get(key, value)
			if value is None or isinstance(value, (str, int, float)) or key in ("style", "class_"):
				attributes[key] = value
			else:
				del attributes[key]
		attributes.update(self.__attributes__)

		# `live = True` is a framework setting, not an HTML attribute; mark live
		# components so the browser knows to open a stream
		attributes.pop("live", None)
		attributes.pop("optimistic", None)
		attributes.pop("optimistic_states", None)
		if self.is_live():
			attributes["data_live"] = True

		# Extra classes from class_="a b" (or a list) come after the component's own
		for key in ("class", "class_"):
			extra = attributes.pop(key, None)
			if isinstance(extra, str):
				extra = extra.split()
			for name in extra or []:
				if name not in class_names:
					class_names.append(name)
		if class_names:
			html += f" class=\"{escape(' '.join(class_names))}\""

		# Only emit an id when something needs it: an explicit id, an id that was
		# used (events, after(), element styles, user code), or a component
		# (a subclass like Counter(t.div)), since callbacks re-render those by id
		if self.__id_used__ or self.__styles__ or is_component:
			attributes['id'] = self.id()
		for key, value in attributes.items():
			if key.startswith('_'):
				continue
			# A trailing underscore avoids Python keywords (for_ -> for)
			if key.endswith("_"):
				key = key[:-1]
			key = key.replace("_", "-")
			if value is None or value is False:
				continue
			# Names aren't escaped, so one from data (t.div(**attrs), <div {attrs}> in a template)
			# mustn't be able to end the tag or add another attribute
			if key not in _attribute_names:
				if INVALID_ATTRIBUTE_NAME.search(key) or not key:
					raise ValueError(f"Invalid attribute name: {key!r}")
				_attribute_names.add(key)
			if key == "style" and isinstance(value, dict):
				value = "; ".join(f"{name.replace('_', '-')}: {css}" for name, css in value.items())
			if value is True:
				html += f" {key}"
				continue
			if callable(value):
				value = url_for(value.__name__)
			html += f" {key}=\"{escape(value)}\""

		html += f">{end}"

		# If it's a void tag or it's None and the tag is in the VOID_TAGS, return the tag without children
		if void or (void is None and tag in VOID_TAGS):
			# A void element can't contain its <style>, so put it right before
			return element_style(level) + html

		# Whitespace inside <pre> and <textarea> is part of what they show (a textarea's value),
		# so their content is written as it is, without the indentation added elsewhere
		closing = f"{indentation}</{tag}>{end}"
		# A Domino template's markup (see domino.dtemplates) is written as its author laid it out,
		# so nothing is added around it either
		verbatim = len(self.__children__) == 1 and getattr(self.__children__[0], "verbatim", False) is True
		if tag in PREFORMATTED_TAGS or verbatim:
			if end:
				html = html[:-len(end)]
			closing = f"</{tag}>{end}"
			level, indent, indentation, end = 0, "", "", ""

		# Escape text unless it's marked safe with Markup or inside <script>/<style>, where only
		# "</script" ("</style") can do harm: "<\/script" means the same in JavaScript (and CSS)
		raw = tag in RAW_TEXT_TAGS
		if raw:
			text = lambda value: RAW_TEXT_END[tag].sub("<\\\\/", str(value))
		else:
			text = lambda value: str(escape(value))

		# Process inner content and children
		if inner:

			inner = text(inner)
	
			# Add indentation to the inner content
			if tag not in PREFORMATTED_TAGS:
				inner = inner.replace("\n", f"{end}{indentation}{indent}")  # Ensure proper indentation for inner content
			inner = f"{indentation}{indent}{inner}{end}"

		inner = element_style(level + 1) + (inner or "")

		# Component CSS goes in the head, before its first stylesheet, so the page's own rules win
		head = tag == "head"

		for child in self.__children__:

			if not isinstance(child, Element) and callable(child):
				child = child()

			if isinstance(child, type):
				child = child()
	
			if isinstance(child, Element):
				if head and child.__tag__ in ("style", "link"):
					inner += styles.place(level + 1, indent)
				try:
					inner += child._render(level + 1, indent)
				except Exception as error:
					note_render_error(error, child)
					note_render_error(error, self)
					raise
			elif isinstance(child, str):
				inner += f"{indentation}{indent}{text(child)}{end}"
			else:
				raise ValueError(f"Invalid child: {child!r}")

		if head:
			inner += styles.place(level + 1, indent)

		# The states this component's predictable handlers lead to, for core.js to show
		# instantly; inert JSON, so it costs the page nothing else
		if predictions:
			inner += f"{indentation}{indent}<script type=\"application/json\" data-domino-predict>{optimistic.script_json(predictions)}</script>{end}"

		if inner:
			html += f"{inner}"

		# Ensure proper indentation for closing tag
		html += closing

		return html


class Style:


	def __init__(self, parent:Domino=None, href="", external=False):

		self.styles = {}
		self.href = href

		if parent and href and not external:

			def style():
			
				return Response(self.compute().inner(), mimetype="text/css")

			parent.add_url_rule(href, href, style)
			

	def style(self, target, rules=None, /, **kwargs):
		"""Add rules for `target` (a selector, a class or one element), as keywords
		(font_size="2rem") and/or a dict that can nest (see domino.css):
		style(".card", {":hover": {...}, "h3": {...}, "@media (max-width: 600px)": {...}})."""

		rules = dict(rules or {}, **kwargs)

		if isinstance(target, str):
			selector = target
		elif isinstance(target, type):
			selector = f'.{css_class_name(target)}'
		elif isinstance(target, Element):
			# Rules for one element travel with that element instead of piling
			# up in this (possibly app-wide) stylesheet
			css.merge(target.__styles__, rules)
			return self
		else:
			raise ValueError(f"Invalid target: {target!r}")

		css.merge(self.styles.setdefault(selector, {}), rules)

		return self


	def theme(self, dark=None, **variables):
		"""CSS variables on :root (primary="#06c" -> --primary, used as var(--primary)),
		with the values in `dark` for visitors whose system prefers a dark color scheme."""

		self.style(":root", {css.variable_name(name): value for name, value in variables.items()})

		if dark:
			# Tells the browser the page has a dark look too, so its own controls (buttons,
			# inputs, scrollbars) are drawn dark then, instead of light under light text
			self.style(":root", color_scheme="light dark")
			self.style("@media (prefers-color-scheme: dark)", {
				":root": {css.variable_name(name): value for name, value in dark.items()}
			})

		return self


	def compute(self, head=None):

		# A <style> whose CSS is computed when the page is done rendering
		return StyleBlock(self, head)


	@staticmethod
	def id_selector(id_):

		# CSS identifiers can't start with a digit (and UUIDs often do), so
		# escape it as a code point, e.g. "#81e4..." -> "#\38 1e4..."
		if id_[:1].isdigit():
			return f"#\\3{id_[0]} {id_[1:]}"

		return f"#{id_}"


	@staticmethod
	def css(styles):

		return css.render(styles)


	def link(self, head=None, href=""):

		if not href:
			href = self.href

		return Element("link", head, rel="stylesheet", href=href)


class StyleBlock(Element):
	"""A <style> holding a Style's rules. Its CSS is computed when the page has finished
	rendering, so rules added while rendering (in render(), say) still apply."""


	def __init__(self, stylesheet, parent=None):

		self.stylesheet = stylesheet

		super().__init__("style", parent)


	def inner(self, inner=None):

		if inner is None:
			return Style.css(self.stylesheet.styles)

		return super().inner(inner)


	def _render(self, level=0, indent=4):

		if isinstance(indent, int):
			indent = " " * indent

		styles = current_styles()
		if styles is None:
			return self._render_now(level, indent)

		# Component CSS goes before the page's own, so the page's rules win
		return styles.place(level, indent) + styles.slot(lambda: self._render_now(level, indent))


	def _render_now(self, level, indent):

		rules = self.inner()
		if not rules:
			return ""

		return Element("style", inner=rules)._render(level, indent)
