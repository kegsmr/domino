import domino.tags as t
from domino import State


class Average(t.p):


	def __init__(self, scores):

		self.scores = scores

		super().__init__()


	def render(self):

		# No scores yet: ZeroDivisionError, shown on the debug error page
		return [
			f"Average: {sum(self.scores) / len(self.scores):.1f}"
		]


class Report(t.section):


	def render(self):

		return [
			t.h2() [
				"Report"
			],
			Average([])
		]


class Mistake(t.section):


	def render(self):

		# render() must give elements and strings: a dict isn't one
		return [
			t.h2() [
				"Mistake"
			],
			{"score": 3}
		]


class Greeting(t.section):
	"""Rendered by its paired template, greeting.html, which uses a name it isn't given."""

	name = State("Ada")
