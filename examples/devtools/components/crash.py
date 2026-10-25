import domino.tags as t


class Crash(t.section):
	"""Buttons whose handlers raise, to see the error overlay."""


	def render(self):

		return [
			t.h2() [
				"Errors"
			],
			t.button(class_="crash", on_click=self.save) [
				"Raise an exception"
			],
			" ",
			t.button(on_click=self.average) [
				"Divide by zero"
			]
		]


	def save(self, event):

		# This button isn't in a form, so event.form is empty: a KeyError, with a hint
		name = event.form["name"]
		print(f"Saving {name}")


	def average(self):

		return mean([])


def mean(values):

	return sum(values) / len(values)
