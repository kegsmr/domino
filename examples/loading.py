import sys
import time

sys.path.append("")

import domino.tags as t
from domino import Domino
from domino.components import Document


app = Domino(__name__)


class Settings(t.div):


	def __init__(self, *args, **kwargs):

		super().__init__(*args, **kwargs)

		self.saves = 0


	def render(self):

		self([
			t.p() [
				f"Saved {self.saves} time(s)"
			],
			save := t.button(class_="save") [
				"Save"
			],
			" ",
			crash := t.button() [
				"Raise an exception"
			]
		])

		save.bind("click", self.save)
		crash.bind("click", self.crash)


	def save(self):

		# Slow work, so the button's loading state is visible
		time.sleep(1.5)
		self.saves += 1

		return self


	def crash(self):

		# In debug mode the browser shows this traceback; otherwise only a generic error
		raise RuntimeError("Something went wrong while saving")


@app.route("/")
def index():

	page = Document(title="Loading and errors") [
		t.h1() [
			"Loading and errors"
		],
		Settings()
	]

	page.style("body", font_family="system-ui, sans-serif", max_width="32rem", margin="2rem auto")
	page.style("button", font="inherit", padding="0.5rem 1rem")

	# Domino marks the button that fired with data-loading (and aria-busy) until the
	# response arrives; the rest is up to your CSS
	page.style("button[data-loading]", opacity="0.6", cursor="progress")
	page.style(".save[data-loading]", font_size="0")
	page.style(".save[data-loading]::after", content="'Saving\\2026'", font_size="1rem")

	return page


if __name__ == "__main__":
	app.run(debug=True)
