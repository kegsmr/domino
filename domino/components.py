from . import tags as t
from .core import Element, Style


class Document(Element):


	def __init__(self, title=None, favicon=None):

		super().__init__(tag="html")

		self.stylesheet = Style()

		self.head = t.head() [
			t.meta(charset='utf-8'),
			t.meta(
				name='viewport',
				content='width=device-width, initial-scale=1'
			),
			self.stylesheet.compute
		]
		if title:
			self.head.add_children([
				t.title() [title]
			])
		if favicon:
			self.head.add_children([
				t.link(rel="icon", type="image/png", href=favicon)
			])

		self.body = t.body()

		self.set_children([
			self.head,
			self.body
		])

		self.content_root = self.body


	def _render(self, level=0, indent=4):

		return "<!DOCTYPE html>\n" + super()._render(level, indent)


	def style(self, target=None, **kwargs):

		if target is None:
			target = self.__class__

		self.stylesheet.style(target, **kwargs)

		return self
