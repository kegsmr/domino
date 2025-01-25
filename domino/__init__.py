from domino.util import *

VOID_TAGS = [
	"area", "base", "br", "col", "embed", "hr", "img",
	"input", "link", "meta", "source", "track", "wbr"
]

class Domino:

	def __init__(self):
		self.decorated = []
		self.tags = []

	def element(self, tag="", inner="", void=None):
		def decorator(cls):
			if tag:
				cls.__tag__ = tag
			if inner:
				cls.__inner__ = inner
			cls.__void__ = void
			self.decorated.append(cls)
			return cls
		return decorator

	def build_hierarchy(self):

		def get_parent(cls):
			if '.' not in cls.__qualname__:
				return None
			enclosing_name = cls.__qualname__.rsplit('.', 1)[0]
			for potential_parent in self.decorated:
				if potential_parent.__qualname__ == enclosing_name:
					return potential_parent
			return None

		hierarchy = {cls: [] for cls in self.decorated}
		for cls in self.decorated:
			parent = get_parent(cls)
			if parent:
				hierarchy[parent].append(cls)

		def build_tuples(cls):
			children = [build_tuples(child) for child in hierarchy[cls]]
			return (cls, children)

		roots = [cls for cls in self.decorated if get_parent(cls) is None]
		if not roots:
			raise ValueError("No root class found in the decorated list.")
		return build_tuples(roots[0])

	def render(self):

		self.structure = self.build_hierarchy()

		def render_html(node, level=0):

			cls, children = node
			tag = getattr(cls, "__tag__", "")
			inner = getattr(cls, "__inner__", "")
			void = getattr(cls, "__void__", None)
			indent = "\t" * level

			class_names = [cls.__name__]
			for base in cls.__bases__:
				if base.__name__ != "object":  # Exclude base "object" class
					class_names.append(base.__name__)
			class_attr = " ".join(class_names)

			html = f"{indent}<{tag} class=\"{class_attr}\""

			for a, v in get_custom_attributes(cls).items():
				html += f" {a}=\"{v}\""

			html += ">"

			if void or void is None and tag in VOID_TAGS:
				return html
			if inner:
				inner = f"{indent}\t{inner}\n"
			if hasattr(cls, "render"):
				inner += f"{indent}\t{cls().render()}\n"
			if children:
				for child in children:
					inner += render_html(child, level + 1)
			if inner:
				html += f"\n{inner}{indent}"
			html += f"</{tag}>\n"

			return html

		return render_html(self.structure)