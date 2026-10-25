import domino.tags as t
from domino import State


# No render(): counter.html next to this file is the template, found by the class's name
class Counter(t.div):

	count = State(0)


	def increment(self):

		self.count += 1


	def reset(self):

		self.count = 0
