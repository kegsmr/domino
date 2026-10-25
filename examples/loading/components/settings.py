import time

import domino.tags as t
from domino import State


class Settings(t.div):

	saves = State(0)


	def render(self):

		return [
			t.p() [
				f"Saved {self.saves} time(s)"
			],
			t.button(class_="save", on_click=self.save) [
				"Save"
			],
			" ",
			t.button(on_click=self.crash) [
				"Raise an exception"
			]
		]


	def save(self):

		# Slow work, so the button's loading state is visible
		time.sleep(1.5)
		self.saves += 1


	def crash(self):

		# In debug mode the browser shows this traceback; otherwise only a generic error
		raise RuntimeError("Something went wrong while saving")
