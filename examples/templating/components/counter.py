import domino.tags as t
from domino import State


# No render(): <Counter> in counter.html, next to this file, is its markup. The Python side is
# only the logic: its State, helpers the template reads, and the handlers its events call
class Counter(t.div):

	count = State(0)


	@property
	def at_zero(self):

		return self.count == 0


	def big(self):

		return self.count >= 5


	def increment(self):

		self.count += 1


	def reset(self):

		self.count = 0
