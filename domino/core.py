from flask import *


VOID_TAGS = [
	"area", "base", "br", "col", "embed", "hr", "img",
	"input", "link", "meta", "source", "track", "wbr"
]


class Domino(Flask):


	def __init__(self, *args, **kwargs):

		super().__init__(*args, **kwargs)

		EVENTS = "/_events"

		self.__events__ = {}

		def event_handler():

			# Retrieve the event data from the incoming JSON payload
			data = request.get_json()

			# Access the event_id sent by the client-side JavaScript
			event_id = data.get("event_id")

			self.__events__[event_id]()
    
			# You can return a JSON response to acknowledge the event
			return jsonify({"status": "success", "event_id": event_id})

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
				if hasattr(result, "render"):
					for event_id, callback in result.__events__.items():
						self.__events__[event_id] = callback
					return result.render()
				else:
					return result
			
			# Set a unique name for the wrapper function
			wrapper.__name__ = function.__name__

			# Apply the Flask route decorator to the wrapper
			return flask_decorator(wrapper)

		return decorator


	def style(self, href="", external=False, **kwargs):

		return Style(self, href, external, **kwargs)


class Element:


	__show__ = False


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

		self.tag(tag)
		self.parent(parent)
		self.void(void)
		self.configure(**kwargs)

		if inner:
			self.inner(inner)
		else:
			self.inner()


	def parent(self, parent=None):
		if parent:
			if self.__parent__:
				self.__parent__.__children__.remove(self)
			self.__parent__ = parent
			if self not in self.__parent__.__children__:
				self.__parent__.__children__.append(self)
			# print(f"{self} {self.__parent__.__children__}")
		return self.__parent__
	

	def root(self):
		root = self
		while root.parent():
			root = root.parent()
		return root


	def tag(self, tag=None):
		if tag:
			self.__tag__ = tag
		return self.__tag__
	

	def inner(self, inner=None):
		if inner:
			self.__inner__ = inner
		return self.__inner__
	

	def void(self, void=None):
		if void:
			self.__void__ = void
		return self.__void__


	def configure(self, **kwargs):
		for key, value in kwargs.items():
			self.__attributes__[key.replace("_", "-")] = value


	def state(self, value):
		
		state_id = len(self.__states__)

		self.__states__.setdefault(state_id, value)

		def set_value(value):

			self.__states__[state_id] = value

			#TODO re-render component

		return self.__states__[state_id], set_value


	def bind(self, event, callback):

		#print(f"Binding {callback} to {self} on event {event}")

		event = event.lower()

		element_id = id(self)
		event_id = f"event-{element_id}-{event}"

		root = self.root()
		root.__events__[event_id] = callback
		
		self.configure(data_event_id=event_id)

		# Generate JavaScript to handle the event
		script = f"""
		document.addEventListener('DOMContentLoaded', function() {{
			document.querySelector('[data-event-id=\"{event_id}\"]').addEventListener('{event}', function() {{
				fetch('/_events', {{
					method: 'POST',
					headers: {{ 'Content-Type': 'application/json' }},
					body: JSON.stringify({{ 'event_id': '{event_id}' }})
				}});
			}});
		}});
		"""
			
		# Inject the script into the parent component (or elsewhere as needed)
		Element("script", self.parent(), script)


	def render(self, level=0, indent=4) -> str:
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

		# Handle class names if the tag is not "html"
		if tag != "html":
			class_names = []
			for base in (self.__class__,) + self.__class__.__bases__:
				if base.__name__ not in ["object", "Element"] and tag != base.__name__:
					class_names.append(base.__name__)
			class_attr = " ".join(class_names)
			if len(class_names) > 0:
				html += f" class=\"{class_attr}\""

		# Add attributes
		for key, value in self.__attributes__.items():
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
			inner += child.render(level + 1, indent)

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
		
		if type(target) is str:
			name = target
		else:
			if isinstance(target, type):
				cls = target
				tag = ""
			else:
				cls = target.__class__
				tag = target.__tag__
			if tag == cls.__name__:
				name = cls.__name__
			else:
				name = "." + cls.__name__

		self.styles.setdefault(name, {})

		for key, value in kwargs.items():
			self.styles[name][key] = value


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