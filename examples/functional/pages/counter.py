from domino import State
import domino.tags as t


# A page can be a component: each visit gets a new one. Links between pages swap them in
# without reloading, and this page's buttons work as soon as it's shown
class Page(t.section):

	count = State(0)


	def render(self):

		return [
			t.h1() [
				"Counter"
			],
			t.p() [
				f"Clicked {self.count} times"
			],
			t.button(on_click=self.increment) [
				"Click me"
			]
		]


	def increment(self):

		self.count += 1
