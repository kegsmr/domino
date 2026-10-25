import sys
import random

sys.path.append("")

import domino.tags as t
from domino import Domino
from domino.components import Document


app = Domino(__name__)


class RandomNumber(t.div):


	def __init__(self, *args, **kwargs):

		super().__init__(*args, **kwargs)

		self.number = 0


	def render(self):

		self([
			t.p() [
				f"Current number: {self.number}"
			]
		])

		self.after(1000, self.roll)


	def roll(self):

		self.number = random.randint(0, 1000)

		return self


@app.route("/")
def index():

	return Document(title="Random Number") [
		t.h1() [
			"Random Number"
		],
		RandomNumber()
	]


if __name__ == "__main__":
	app.run(debug=True)
