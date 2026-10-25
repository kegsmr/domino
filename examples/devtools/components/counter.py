import domino.tags as t
from domino import State


class Counter(t.section):
	"""Its handlers only change its own State, so the inspector shows them as instant."""

	count = State(0)
	step = State(1)


	def render(self):

		return [
			t.h2() [
				"Counter"
			],
			t.p() [
				f"Count: {self.count}"
			],
			t.button(on_click=self.decrement) [
				f"-{self.step}"
			],
			" ",
			t.button(on_click=self.increment) [
				f"+{self.step}"
			],
			" ",
			t.button(on_click=self.bigger_steps) [
				"Bigger steps"
			]
		]


	def increment(self):

		self.count += self.step


	def decrement(self):

		self.count -= self.step


	def bigger_steps(self):

		if self.step < 100:
			self.step = self.step * 10
