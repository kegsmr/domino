from flask import *

# from domino.util import *


VOID_TAGS = [
	"area", "base", "br", "col", "embed", "hr", "img",
	"input", "link", "meta", "source", "track", "wbr"
]


class Domino(Flask):

	pass

	# def __init__(self):

	# 	pass


	# def document(self):

	# 	return self.element("html")


	# def element(self, tag="", inner="", void=None, **kwargs):

	# 	def decorator(cls):

	# 		#print(cls)

	# 		#self.elements.append(cls)

	# 		if tag:
	# 			cls.__tag__ = tag
	# 		if inner:
	# 			cls.__inner__ = inner
	# 		if void is not None:
	# 			cls.__void__ = void
	# 		cls.__attributes__ = kwargs

	# 		# If the class has its own __init__, preserve it
	# 		if hasattr(cls, "__init__"):
	# 			original_init = cls.__init__
	# 		else:
	# 			original_init = None  # If no __init__ exists, we don't need to call anything

	# 		# Define the new __init__ method
	# 		def __init__(self, parent=None, *args, **kwargs):

	# 			#print(f"Initializing {self} within {parent}...")

	# 			if parent:
	# 				if not hasattr(parent, "__children__"):
	# 					parent.__children__ = []
	# 				parent.__children__.append(self)

	# 			# Call the original __init__ if it exists
	# 			if original_init:
	# 				original_init(self, *args, **kwargs)

	# 		def _render(self, level=0) -> str:

	# 			# print(f"Rendering {self}...")

	# 			if hasattr(self, "__children__"):
	# 				children = self.__children__
	# 			else:
	# 				children = None

	# 			tag = getattr(self, "__tag__", "")
	# 			inner = getattr(self, "__inner__", "")
	# 			void = getattr(self, "__void__", None)
	# 			indent = "\t" * level

	# 			html = f"{indent}<{tag}"

	# 			if tag != "html":
	# 				class_names = [self.__class__.__name__]
	# 				for base in self.__class__.__bases__:
	# 					if base.__name__ != "object":  # Exclude base "object" class
	# 						class_names.append(base.__name__)
	# 				class_attr = " ".join(class_names)
	# 				if len(class_names) > 0:
	# 					html += f" class=\"{class_attr}\""

	# 			for key, value in self.__attributes__.items():
	# 				html += f" {key}=\"{value}\""

	# 			html += ">"

	# 			if void or void is None and tag in VOID_TAGS:
	# 				return html
	# 			if inner:
	# 				inner = f"{indent}\t{inner}\n"
	# 			# if hasattr(self, "render"):
	# 			# 	inner += f"{indent}\t{self().render()}\n"
	# 			if children:
	# 				for child in children:
	# 					inner += child.render(level + 1)
	# 			if inner:
	# 				html += f"\n{inner}{indent}"
	# 			html += f"</{tag}>\n"

	# 			return html
			
	# 		def _configure(self, **kwargs):
	# 			for key, value in kwargs.items():
	# 				self.__attributes__[key] = value

	# 		def _inner(self, inner):
	# 			self.__inner__ = inner

	# 		cls.__init__ = __init__

	# 		cls.render = _render
	# 		cls.configure = _configure
	# 		cls.inner = _inner

	# 		return cls
		
	# 	return decorator


	# def render(self, document):

	# 	return document.render()


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


	def __init__(self):

		self.styles = {}


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


	def compute(self, head):

		css = []

		for name, properties in self.styles.items():

			# Start the class block
			css.append(f"{name} " + "{")

			# Add each property-value pair
			for key, value in properties.items():
				css.append(f"\t{key.replace('_', '-')}: {value};")

			# End the class block
			css.append("}")

		# Join all parts with newlines for readability
		css = "\n".join(css)

		return Element("style", head, css)