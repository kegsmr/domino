import domino.tags as t
from domino import State


class CounterComponent(t.div):

	# Per-component state; changing it re-renders the component
	count = State(0)


	def render(self):

		return [
			t.p() [
				f"Current Count: {self.count}"
			],
			t.button(on_click=self.increment) [
				"Increment"
			],
			t.button(on_click=self.decrement) [
				"Decrement"
			]
		]


	def increment(self):

		self.count += 1


	def decrement(self):

		self.count -= 1
