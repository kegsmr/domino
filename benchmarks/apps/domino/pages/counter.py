import domino.tags as t
from domino import State


class Page(t.div):

	count = State(0)


	def render(self):

		return [
			t.button(id="inc", on_click=self.increment) [
				"+1"
			],
			t.span(id="count") [
				f"{self.count}"
			]
		]


	def increment(self):

		self.count += 1
