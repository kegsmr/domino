from flask import *


VOID_TAGS = [
	"area", "base", "br", "col", "embed", "hr", "img",
	"input", "link", "meta", "source", "track", "wbr"
]


class Domino(Flask):


	def route(self, rule, **options):

		# Get the original route decorator
		flask_decorator = super().route(rule, **options)

		def decorator(function):

			# Define a new wrapper function
			def wrapper(*args, **kwargs):
				
				# Call the original handler function
				result = function(*args, **kwargs)
				
				# Check if the result has a `render` or `compute` method
				if hasattr(result, "render"):
					return result.render()
				elif hasattr(result, "compute"):
					return result.compute().inner()
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


	def __init__(self, tag=None, parent=None, inner=None, void=None, **kwargs):

		# print(f"Initializing {self} within {parent}")

		self.__children__ = []
		self.__parent__ = None
		self.__tag__ = ""
		self.__inner__ = ""
		self.__void__ = None
		self.__attributes__ = {}

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
			self.__attributes__[key] = value

	
	def bind(self, event, function):
		print(f"Binding {function} to {self} event {event}")


	def render(self, level=0) -> str:

		# print(f"{self} {self.__children__}")

		tag = self.__tag__
		inner = self.__inner__
		void = self.__void__

		if inner is None:
			inner = ""

		indent = "\t" * level

		html = f"{indent}<{tag}"

		if tag != "html":
			class_names = []
			for base in (self.__class__,) + self.__class__.__bases__:
				if base.__name__ not in ["object", "Element"]:  # Exclude base "object" class
					class_names.append(base.__name__)
			class_attr = " ".join(class_names)
			if len(class_names) > 0:
				html += f" class=\"{class_attr}\""

		for key, value in self.__attributes__.items():
			html += f" {key}=\"{value}\""

		html += ">"

		if void or void is None and tag in VOID_TAGS:
			return html
		if inner:
			inner = inner.replace("\n", f"\n{indent}\t")
			inner = f"{indent}\t{inner}\n"
		# if hasattr(self, "render"):
		# 	inner += f"{indent}\t{self().render()}\n"
		for child in self.__children__:
			inner += child.render(level + 1)
		if inner:
			html += f"\n{inner}{indent}"
		html += f"</{tag}>\n"

		return html
	

class Style:


	def __init__(self, parent:Domino=None, href="", external=False):

		self.styles = {}
		self.href = href

		if parent and href and not external:

			def style():
			
				return Response(self.compute().inner(), mimetype="text/css")

			parent.add_url_rule(href, "stylesheet", style)
			


	def style(self, target, **kwargs):
		
		if type(target) is str:
			name = target
		else:
			if isinstance(target, type):
				cls = target
			else:
				cls = target.__class__
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