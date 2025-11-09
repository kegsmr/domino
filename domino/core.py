from __future__ import annotations

import uuid

from flask import *

from .util import *


VOID_TAGS = [
	"area", "base", "br", "col", "embed", "hr", "img",
	"input", "link", "meta", "source", "track", "wbr"
]


class Domino(Flask):


	__events__ = {}


	def __init__(self, *args, **kwargs):

		super().__init__(*args, **kwargs)

		EVENTS = "/_events"

		def event_handler():

			# Retrieve the event data from the incoming JSON payload
			data = request.get_json()

			# Access the event_id sent by the client-side JavaScript
			event_id = data.get("event_id")

			element, callback = Domino.__events__[event_id]

			result = callback()
			result.init()

			return jsonify({
				"id": result.id(),
				"html": result.render()
			})

		self.add_url_rule(EVENTS, EVENTS, event_handler, methods=["POST"])


	def route(self, rule, **options):

		# Get the original route decorator
		flask_decorator = super().route(rule, **options)

		def decorator(function):

			# Define a new wrapper function
			def wrapper(*args, **kwargs):
				
				# Call the original handler function
				result = function(*args, **kwargs)
				
				# Check if the result has a `render` method
				if hasattr(result, "_render"):
					for event_id, callback in result.__events__.items():
						self.__events__[event_id] = (callback, result)
					return result._render()
				else:
					return result
			
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
		self.__events__ = {}
		self.__id__ = uuid.uuid4()

		self.tag(tag)
		self.parent(parent)
		self.inner(inner)
		self.void(void)
		self.configure(**kwargs)

		self.content_root: Element = self


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

		event = event.lower()

		event_id = f"event-{self.id()}-{event}"
		self.configure(data_event_id=event_id)

		Domino.__events__[event_id] = (self, callback)

		script = """
			function bindDominoEvents() {
				document.querySelectorAll('[data-event-id]').forEach(el => {
					const eventId = el.dataset.eventId;
					const eventType = eventId.split('-').pop();
					if (el.dataset.bound) return; // prevent rebinding
					el.dataset.bound = true;

					el.addEventListener(eventType, function() {
						fetch('/_events', {
							method: 'POST',
							headers: { 'Content-Type': 'application/json' },
							body: JSON.stringify({ event_id: eventId })
						})
						.then(response => response.json())
						.then(data => {
							const target = document.getElementById(data.id);
							if (target) {
								target.outerHTML = data.html;
								bindDominoEvents(); // rebind events in the new HTML
							}
						})
						.catch(err => console.error('Domino event error:', err));
					});
				});
			}

			document.addEventListener('DOMContentLoaded', bindDominoEvents);
		"""

		self.add_children([
			Element('script') [
				script
			]
		])

		return self


	def _render(self, level=0, indent=4) -> str:

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
			if value:
				if callable(value):
					value = url_for(value.__name__)
				html += f" {key}=\"{value}\""

		html += f">{end}"

		# If it's a void tag or it's None and the tag is in the VOID_TAGS, return the tag without children
		if void or (void is None and tag in VOID_TAGS):
			return html

		# Process inner content and children
		if inner:
	
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
				inner += f"{indentation}{indent}{child}{end}"
			else:
				raise ValueError(f"Invalid child: {child!r}")

		if inner:
			html += f"{inner}"

		# Ensure proper indentation for closing tag
		html += f"{indentation}</{tag}>{end}"

		return html


	def after(self, delay, func):

		#TODO

		return self

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