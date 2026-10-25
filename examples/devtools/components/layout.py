import domino.tags as t


class Layout(t.div):
	"""The navigation and the page's content; a component, so it shows in the component stack."""

	css = {
		"nav": {"display": "flex", "gap": "1rem", "padding_bottom": ".75rem", "border_bottom": "1px solid #ddd", "margin_bottom": "1.5rem"},
		"nav a": {"color": "#2a6fdb"},
	}


	def __init__(self, content):

		self.content = content

		super().__init__()


	def render(self):

		return [
			t.nav() [
				t.a(href="/") ["Home"],
				t.a(href="/broken/render") ["A page whose render fails"],
				t.a(href="/broken/child") ["A render returning a dict"],
				t.a(href="/broken/template") ["A template error"],
			],
			t.main() [
				self.content
			]
		]
