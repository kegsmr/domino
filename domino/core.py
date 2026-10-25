from __future__ import annotations

import threading
import time
import traceback
import uuid
import weakref
from collections import OrderedDict
from pathlib import Path

from flask import *
from markupsafe import Markup, escape

from .settings import load_settings
from .util import *
from . import reactive


VOID_TAGS = [
	"area", "base", "br", "col", "embed", "hr", "img",
	"input", "link", "meta", "source", "track", "wbr"
]

# Elements whose text content is not HTML and must not be escaped
RAW_TEXT_TAGS = ["script", "style"]


_render_state = threading.local()

# Guards Element.__pages__, which request threads add to while refresh() reads it
_pages_lock = threading.Lock()


def render_stack():
	"""Components whose render() is running in this thread, innermost last."""

	if not hasattr(_render_state, "stack"):
		_render_state.stack = []

	return _render_state.stack


class Page:
	"""Event registry for one rendered page (one page load in one browser tab)."""


	def __init__(self):

		self.id = str(uuid.uuid4())
		self.events = {}
		self.lock = threading.RLock()  # serializes events for this page
		self.version = 0  # bumped per update, so the browser can drop stale responses
		self.live = False  # shows a live component, so the browser opens a stream
		self.components = set()  # live components shown here, kept alive as long as the page
		self.updates = {}  # element id -> html not yet sent to the browser
		self.updates_ready = threading.Condition()
		self.stream = None  # the newest stream; older ones stop
		self.touch()


	def touch(self):

		self.last_access = time.monotonic()


	def register(self, event_id, element, callback):

		self.events[event_id] = (element, callback)


	def subtree_events(self, root):
		"""This page's events bound to `root` or its descendants."""

		elements = set()
		stack = [root]
		while stack:
			element = stack.pop()
			if isinstance(element, Element) and id(element) not in elements:
				elements.add(id(element))
				stack.extend(element.__children__)

		return {event_id: event for event_id, event in self.events.items() if id(event[0]) in elements}


	def unregister_subtree(self, root):

		# Drop events bound to `root` or its descendants; they are about to be
		# replaced in the browser and would otherwise leak
		for event_id in self.subtree_events(root):
			del self.events[event_id]


	def push(self, element_id, html):
		"""Queue a re-rendered component for this page's stream. Call with self.lock held."""

		self.version += 1

		with self.updates_ready:
			# A newer render replaces one the browser hasn't received yet; moving
			# it to the end keeps it after any parent re-rendered in between
			self.updates.pop(element_id, None)
			self.updates[element_id] = {"id": element_id, "html": html, "version": self.version}
			self.updates_ready.notify_all()


	def open_stream(self):

		token = object()

		with self.updates_ready:
			self.stream = token
			self.updates_ready.notify_all()

		return token


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
	"""What the browser sent with an event: the element's value and its form's fields."""


	def __init__(self, type, value=None, form=None):

		self.type = type
		self.value = value
		self.form = form or {}


	@staticmethod
	def from_request(event_id, data):

		if not isinstance(data, dict):
			data = {}

		form = data.get("form")
		if not isinstance(form, dict):
			form = {}

		type_ = "after" if event_id.startswith("after-") else event_id.rsplit("-", 1)[-1]

		return Event(type_, data.get("value"), form)


	def __repr__(self):

		return f"Event(type={self.type!r}, value={self.value!r}, form={self.form!r})"


class Domino(Flask):


	def __init__(self, *args, page_store: PageStore = None, settings: str = None, **kwargs):

		super().__init__(*args, **kwargs)

		self.config.setdefault("DOMINO_PAGE_TTL", 30 * 60)  # seconds of inactivity
		self.config.setdefault("DOMINO_MAX_PAGES", 1000)
		self.config.setdefault("DOMINO_KEEPALIVE", 15)  # seconds between stream keepalives

		# settings.json < settings.local.json < DOMINO_* environment variables
		self.settings = load_settings(self.root_path, settings)
		self._apply_settings()

		# Named Collections find MongoDB through these settings (mongo.url)
		from . import mongo
		mongo.use_app(self)

		self.page_store = page_store or MemoryPageStore()

		with open(Path(__file__).parent / 'core.js', encoding='utf-8') as js_file:
			CORE_JS = js_file.read()

		self._add_static_route('/_domino/core', CORE_JS)
		self._add_event_handler('/_domino/events')
		self._add_stream('/_domino/stream')


	def _apply_settings(self):

		# {"domino": {"page_ttl": 600}} -> DOMINO_PAGE_TTL; changes made in code later still win
		for key, value in (self.settings.get("domino") or {}).items():
			self.config[f"DOMINO_{key.upper()}"] = value

		if self.settings.get("secret_key"):
			self.secret_key = self.settings["secret_key"]


	def _add_event_handler(self, route):

		def event_handler():

			# Retrieve the event data from the incoming JSON payload
			data = request.get_json(silent=True) or {}

			# Access the page_id and event_id sent by the client-side JavaScript
			page = self._get_page(data.get("page_id")) or DEFAULT_PAGE
			event_id = data.get("event_id")

			# Reactive changes the callback makes re-render their subscribers once the page
			# lock is released (updating other pages while holding it could deadlock)
			with reactive.batch(background=True) as changes, page.lock:

				event = page.events.get(event_id) or DEFAULT_PAGE.events.get(event_id)
				if event is None:
					return jsonify({"error": "Unknown or expired event"}), 404

				g.domino_page = page

				_, callback = event

				try:
					if accepts_argument(callback):
						result = callback(Event.from_request(event_id, data.get("data")))
					else:
						result = callback()

					if not isinstance(result, Element):
						return jsonify({"id": None, "html": None})

					# Old binds must go before rendering so the new ones register fresh.
					# If rendering fails the browser still shows the old HTML, so put
					# the old events back and drop any the failed render added
					events = dict(page.events)
					page.unregister_subtree(result)
					try:
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

				return jsonify({
					"id": result.id(),
					"html": html,
					"version": page.version
				})

		self.add_url_rule(route, route, event_handler, methods=["POST"])


	def _event_error(self, event_id, error):

		self.logger.exception("Domino event %s failed", event_id)

		# Tracebacks can reveal code and data, so only send them while debugging
		if not self.debug:
			return jsonify({"error": "Internal Server Error"}), 500

		return jsonify({
			"error": f"{type(error).__name__}: {error}",
			"traceback": traceback.format_exc(),
			"debug": True
		}), 500


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


	def _new_page(self):

		page = Page()

		self.page_store.save(page)
		self._prune_pages()

		g.domino_page = page

		return page


	def _get_page(self, page_id):

		self._prune_pages()

		return self.page_store.load(page_id) if page_id else None


	def _drop_page(self, page):

		self.page_store.delete(page.id)


	def _prune_pages(self):

		self.page_store.prune(self.config["DOMINO_PAGE_TTL"], self.config["DOMINO_MAX_PAGES"])


	def _add_static_route(self, route, data):

		self.add_url_rule(route, route, lambda: Response(data, mimetype="text/javascript"), methods=["GET"])


	def route(self, rule, **options):

		# Get the original route decorator
		flask_decorator = super().route(rule, **options)

		def decorator(function):

			# Define a new wrapper function
			def wrapper(*args, **kwargs):
				
				# Events bound while building and rendering this response belong to a new page
				page = self._new_page()

				# Call the original handler function
				result = function(*args, **kwargs)

				# Check if the result has a `render` method
				if hasattr(result, "_render"):
					result.configure(data_domino_page=page.id)
					html = result._render()
				else:
					html = result

				# Don't keep pages that have nothing to handle or refresh
				if not page.events and not page.live:
					self._drop_page(page)

				return html
			
			# Set a unique name for the wrapper function
			wrapper.__name__ = function.__name__

			# Apply the Flask route decorator to the wrapper
			return flask_decorator(wrapper)

		return decorator


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


	def is_live(self):
		"""Whether pages showing this component need a stream for refresh()."""

		return getattr(type(self), "live", False) is True or bool(self.__dependencies__)


	def refresh(self, skip=None):
		"""Re-render this component and push it to every live page showing it (except `skip`)."""

		with _pages_lock:
			pages = [page for page in self.__pages__ or () if page is not skip]

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
				html = self._render()
			finally:
				_render_state.page = previous
			events = first.subtree_events(self)
			first.push(self.id(), html)

		for page in pages[1:]:
			with page.lock:
				page.unregister_subtree(self)
				page.events.update(events)
				page.push(self.id(), html)

		return self


	def _render(self, level=0, indent=4) -> str:

		if hasattr(self, 'render'):
			# Remember where this component is shown so refresh() can update it there
			page = Page.current()
			if page is not DEFAULT_PAGE:
				with _pages_lock:
					if self.__pages__ is None:
						self.__pages__ = weakref.WeakSet()
					self.__pages__.add(page)

			# Subscriptions are rebuilt by whatever this render reads
			reactive.forget(self)
			render_stack().append([self, 0])
			try:
				self.render()
			finally:
				render_stack().pop()

			if page is not DEFAULT_PAGE and self.is_live():
				page.live = True
				page.components.add(self)

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
			css = Style.css({Style.id_selector(self.id()): self.__styles__})
			return Element("style", inner=css)._render(style_level, indent)

		html = f"{indentation}<{tag}"

		# Handle class names: every class in the hierarchy except the tag itself,
		# so mixins and parent components (e.g. col_6 -> col-6) are kept
		class_names = []
		for base in self.__class__.__mro__:
			if base in (object, Element) or base.__name__ == tag or base.__module__ == "domino.tags":
				continue
			name = css_class_name(base)
			if name not in class_names:
				class_names.append(name)
		is_component = len(class_names) > 0

		# Add attributes
		attributes = get_class_attributes(self)
		if "class" in attributes:
			attributes.pop("class")
		attributes.update(self.__attributes__)

		# `live = True` is a framework setting, not an HTML attribute; mark live
		# components so the browser knows to open a stream
		attributes.pop("live", None)
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

		# Escape text unless it's marked safe with Markup or inside <script>/<style>
		raw = tag in RAW_TEXT_TAGS
		text = (lambda value: str(value)) if raw else (lambda value: str(escape(value)))

		# Process inner content and children
		if inner:

			inner = text(inner)
	
			# Add indentation to the inner content
			inner = inner.replace("\n", f"{end}{indentation}{indent}")  # Ensure proper indentation for inner content
			inner = f"{indentation}{indent}{inner}{end}"

		inner = element_style(level + 1) + (inner or "")

		for child in self.__children__:

			if not isinstance(child, Element) and callable(child):
				child = child()

			if isinstance(child, type):
				child = child()
	
			if isinstance(child, Element):
				inner += child._render(level + 1, indent)
			elif isinstance(child, str):
				inner += f"{indentation}{indent}{text(child)}{end}"
			else:
				raise ValueError(f"Invalid child: {child!r}")

		if inner:
			html += f"{inner}"

		# Ensure proper indentation for closing tag
		html += f"{indentation}</{tag}>{end}"

		return html


class Style:


	def __init__(self, parent:Domino=None, href="", external=False):

		self.styles = {}
		self.href = href

		if parent and href and not external:

			def style():
			
				return Response(self.compute().inner(), mimetype="text/css")

			parent.add_url_rule(href, href, style)
			

	def style(self, target, **kwargs):
		
		if isinstance(target, str):
			selector = target
		elif isinstance(target, type):
			selector = f'.{css_class_name(target)}'
		elif isinstance(target, Element):
			# Rules for one element travel with that element instead of piling
			# up in this (possibly app-wide) stylesheet
			target.__styles__.update(kwargs)
			return
		else:
			raise ValueError(f"Invalid target: {target!r}")

		self.styles.setdefault(selector, {})

		for key, value in kwargs.items():
			self.styles[selector][key] = value


	def compute(self, head=None):

		# Return the CSS as a <style> element
		return Element("style", head, Style.css(self.styles))


	@staticmethod
	def id_selector(id_):

		# CSS identifiers can't start with a digit (and UUIDs often do), so
		# escape it as a code point, e.g. "#81e4..." -> "#\38 1e4..."
		if id_[:1].isdigit():
			return f"#\\3{id_[0]} {id_[1:]}"

		return f"#{id_}"


	@staticmethod
	def css(styles):

		css = []

		for name, properties in styles.items():
		
			base_styles = []
			hover_styles = {}

			# Separate normal and hover styles
			for key, value in properties.items():
				if isinstance(value, dict) and key == "hover":
					hover_styles = value  # Store hover styles
				else:
					base_styles.append(f"\t{key.replace('_', '-')}: {value};")

			# Add base styles to the CSS block
			css.append(f"{name} " + "{")
			css.extend(base_styles)
			css.append("}")

			# Add hover styles to the CSS block
			if hover_styles:
				css.append(f"{name}:hover " + "{")
				for hover_key, hover_value in hover_styles.items():
					css.append(f"\t{hover_key.replace('_', '-')}: {hover_value};")
				css.append("}")

		# Join all parts with newlines for readability
		return "\n".join(css)
			
	
	def link(self, head=None, href=""):

		if not href:
			href = self.href

		return Element("link", head, rel="stylesheet", href=href)