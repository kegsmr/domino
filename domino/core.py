from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from flask import *
from markupsafe import Markup, escape

from .util import *


VOID_TAGS = [
	"area", "base", "br", "col", "embed", "hr", "img",
	"input", "link", "meta", "source", "track", "wbr"
]

# Elements whose text content is not HTML and must not be escaped
RAW_TEXT_TAGS = ["script", "style"]


class Page:
	"""Event registry for one rendered page (one page load in one browser tab)."""


	def __init__(self):

		self.id = str(uuid.uuid4())
		self.events = {}
		self.touch()


	def touch(self):

		self.last_access = time.monotonic()


	def register(self, event_id, element, callback):

		self.events[event_id] = (element, callback)


	def unregister_subtree(self, root):

		# Drop events bound to `root` or its descendants; they are about to be
		# replaced in the browser and would otherwise leak
		elements = set()
		stack = [root]
		while stack:
			element = stack.pop()
			if isinstance(element, Element) and id(element) not in elements:
				elements.add(id(element))
				stack.extend(element.__children__)

		for event_id, (element, _) in list(self.events.items()):
			if id(element) in elements:
				del self.events[event_id]


	@staticmethod
	def current():

		if has_app_context() and "domino_page" in g:
			return g.domino_page

		return DEFAULT_PAGE


# Used for events bound outside of a request (e.g. at import time)
DEFAULT_PAGE = Page()


class Domino(Flask):


	def __init__(self, *args, **kwargs):

		super().__init__(*args, **kwargs)

		self.config.setdefault("DOMINO_PAGE_TTL", 30 * 60)  # seconds of inactivity
		self.config.setdefault("DOMINO_MAX_PAGES", 1000)

		self._pages = {}
		self._pages_lock = threading.Lock()

		with open(Path(__file__).parent / 'core.js', encoding='utf-8') as js_file:
			CORE_JS = js_file.read()

		self._add_static_route('/_domino/core', CORE_JS)
		self._add_event_handler('/_domino/events')


	def _add_event_handler(self, route):

		def event_handler():

			# Retrieve the event data from the incoming JSON payload
			data = request.get_json(silent=True) or {}

			# Access the page_id and event_id sent by the client-side JavaScript
			page = self._get_page(data.get("page_id")) or DEFAULT_PAGE
			event_id = data.get("event_id")

			event = page.events.get(event_id) or DEFAULT_PAGE.events.get(event_id)
			if event is None:
				return jsonify({"error": "Unknown or expired event"}), 404

			g.domino_page = page

			_, callback = event

			result = callback()

			if not isinstance(result, Element):
				return jsonify({"id": None, "html": None})

			page.unregister_subtree(result)

			return jsonify({
				"id": result.id(),
				"html": result._render()
			})

		self.add_url_rule(route, route, event_handler, methods=["POST"])


	def _new_page(self):

		page = Page()

		with self._pages_lock:
			self._pages[page.id] = page
			self._prune_pages()

		g.domino_page = page

		return page


	def _get_page(self, page_id):

		with self._pages_lock:
			self._prune_pages()
			page = self._pages.get(page_id)
			if page:
				page.touch()

		return page


	def _drop_page(self, page):

		with self._pages_lock:
			self._pages.pop(page.id, None)


	def _prune_pages(self):

		# Caller must hold self._pages_lock
		cutoff = time.monotonic() - self.config["DOMINO_PAGE_TTL"]
		for page_id, page in list(self._pages.items()):
			if page.last_access < cutoff:
				del self._pages[page_id]

		excess = len(self._pages) - self.config["DOMINO_MAX_PAGES"]
		if excess > 0:
			oldest = sorted(self._pages.values(), key=lambda page: page.last_access)
			for page in oldest[:excess]:
				del self._pages[page.id]


	def _add_static_route(self, route, data):

		self.add_url_rule(route, route, lambda: data, methods=["GET"])


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

				# Don't keep pages that have nothing to handle
				if not page.events:
					self._drop_page(page)

				return html
			
			# Set a unique name for the wrapper function
			wrapper.__name__ = function.__name__

			# Apply the Flask route decorator to the wrapper
			return flask_decorator(wrapper)

		return decorator


	def style(self, href="", external=False, **kwargs):

		self.stylesheet = Style(self, href, external, **kwargs)

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
		self.__id__ = uuid.uuid4()

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
			return str(self.__attributes__.get('id') or self.__id__)
		self.__attributes__['id'] = id_
		return self


	def configure(self, **kwargs):
		self.__attributes__.update(kwargs)
		return self


	def bind(self, event, callback):

		event_id = f"event-{self.id()}-{event.lower()}"

		self.configure(data_event_id=event_id)
		Page.current().register(event_id, self, callback)

		return self


	def after(self, delay: int, func):

		event_id = f"after-{self.id()}-{delay}"

		self.configure(data_after_id=event_id)
		Page.current().register(event_id, self, func)

		return self


	def _render(self, level=0, indent=4) -> str:

		if hasattr(self, 'render'):
			self.render()

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

		html = f"{indentation}<{tag}"

		# Handle class names
		class_names = []
		for base in (self.__class__,) + self.__class__.__bases__:
			if base.__name__ not in ["object", "Element"] and tag != base.__name__:
				class_names.append(base.__name__)
		class_attr = " ".join(class_names)
		if len(class_names) > 0:
			html += f" class=\"{class_attr}\""

		# Add attributes
		attributes = get_class_attributes(self)
		if "class" in attributes:
			attributes.pop("class")
		attributes.update(self.__attributes__)
		attributes['id'] = self.id()
		for key, value in attributes.items():
			if key.startswith('_'):
				continue
			key = key.replace("_", "-")
			if value is None or value is False:
				continue
			if value is True:
				html += f" {key}"
				continue
			if callable(value):
				value = url_for(value.__name__)
			html += f" {key}=\"{escape(value)}\""

		html += f">{end}"

		# If it's a void tag or it's None and the tag is in the VOID_TAGS, return the tag without children
		if void or (void is None and tag in VOID_TAGS):
			return html

		# Escape text unless it's marked safe with Markup or inside <script>/<style>
		raw = tag in RAW_TEXT_TAGS
		text = (lambda value: str(value)) if raw else (lambda value: str(escape(value)))

		# Process inner content and children
		if inner:

			inner = text(inner)
	
			# Add indentation to the inner content
			inner = inner.replace("\n", f"{end}{indentation}{indent}")  # Ensure proper indentation for inner content
			inner = f"{indentation}{indent}{inner}{end}"

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
			selector = f'.{target.__name__}'
		elif isinstance(target, Element):
			selector = f'#{target.id()}'
		else:
			raise ValueError(f"Invalid target: {target!r}")

		self.styles.setdefault(selector, {})

		for key, value in kwargs.items():
			self.styles[selector][key] = value


	def compute(self, head=None):

		css = []

		for name, properties in self.styles.items():
		
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
		css = "\n".join(css)

		# Return the CSS as a <style> element
		return Element("style", head, css)
			
	
	def link(self, head=None, href=""):

		if not href:
			href = self.href

		return Element("link", head, rel="stylesheet", href=href)