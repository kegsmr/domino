from flask import current_app, has_app_context

from . import tags as t
from .core import Style
from .settings import script_json


class Core(t.script):


	def __init__(self):

		super().__init__(src='/_domino/core')


class PublicSettings(t.script):
	"""The app's "public" settings, read by core.js into Domino.settings. Renders nothing when empty."""


	def __init__(self):

		super().__init__(type='application/json', id='domino-settings')


	def _render(self, level=0, indent=4):

		public = {}
		if has_app_context():
			public = getattr(current_app, "settings", {}).get("public") or {}

		# Most apps have no public settings; don't add an empty tag to every page
		if not public:
			return ""

		self.inner(script_json(public))

		return super()._render(level, indent)


class Document(t.html):


	def __init__(self, title=None, favicon=None):

		super().__init__()

		self.stylesheet = Style()

		self.head = t.head() [
			t.meta(charset='utf-8'),
			t.meta(
				name='viewport',
				content='width=device-width, initial-scale=1'
			),
			self.stylesheet.compute,
			PublicSettings(),
			Core()
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
