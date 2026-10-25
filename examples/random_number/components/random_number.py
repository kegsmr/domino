import random

import domino.tags as t
from domino import State


class RandomNumber(t.div):

	number = State(0)


	def render(self):

		# Calls roll() a second after this render reaches the browser, so it keeps rolling
		self.after(1000, self.roll)

		return [
			t.p() [
				f"Current number: {self.number}"
			]
		]


	def roll(self):

		self.number = random.randint(0, 1000)
