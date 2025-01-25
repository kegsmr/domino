from domino.util import *

VOID_TAGS = [
	"area", "base", "br", "col", "embed", "hr", "img",
	"input", "link", "meta", "source", "track", "wbr"
]

class Domino:


	def __init__(self):

		pass


	def document(self):

		return self.element("html")


	def element(self, tag="", inner="", void=None, **kwargs):

		def decorator(cls):

			#print(cls)

			#self.elements.append(cls)

			if tag:
				cls.__tag__ = tag
			if inner:
				cls.__inner__ = inner
			if void is not None:
				cls.__void__ = void
			cls.__attributes__ = kwargs

			# If the class has its own __init__, preserve it
			if hasattr(cls, "__init__"):
				original_init = cls.__init__
			else:
				original_init = None  # If no __init__ exists, we don't need to call anything

			# Define the new __init__ method
			def __init__(self, parent=None, *args, **kwargs):

				#print(f"Initializing {self} within {parent}...")

				if parent:
					if not hasattr(parent, "__children__"):
						parent.__children__ = []
					parent.__children__.append(self)

				# Call the original __init__ if it exists
				if original_init:
					original_init(self, *args, **kwargs)

			def _render(self, level=0) -> str:

				# print(f"Rendering {self}...")

				if hasattr(self, "__children__"):
					children = self.__children__
				else:
					children = None

				tag = getattr(self, "__tag__", "")
				inner = getattr(self, "__inner__", "")
				void = getattr(self, "__void__", None)
				indent = "\t" * level

				html = f"{indent}<{tag}"

				if tag != "html":
					class_names = [self.__class__.__name__]
					for base in self.__class__.__bases__:
						if base.__name__ != "object":  # Exclude base "object" class
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
					inner = f"{indent}\t{inner}\n"
				# if hasattr(self, "render"):
				# 	inner += f"{indent}\t{self().render()}\n"
				if children:
					for child in children:
						inner += child.render(level + 1)
				if inner:
					html += f"\n{inner}{indent}"
				html += f"</{tag}>\n"

				return html
			
			def _configure(self, **kwargs):
				for key, value in kwargs.items():
					self.__attributes__[key] = value

			def _inner(self, inner):
				self.__inner__ = inner

			cls.__init__ = __init__

			cls.render = _render
			cls.configure = _configure
			cls.inner = _inner

			return cls
		
		return decorator


	def render(self, document):

		return document.render()