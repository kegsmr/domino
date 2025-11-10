import sys
import random

sys.path.append("")

import domino.tags as t
from domino import Domino
from domino.components import Document


app = Domino(__name__)


class CounterComponent(t.div):


	def __init__(self, *args, **kwargs):

		super().__init__(*args, **kwargs)

		self.count = 0


	def render(self):

		self([
			t.p() [
				f"Current Count: {self.count}"
			]
		])

		self.after(100, self.update_count)


	def update_count(self):

		self.count = random.randint(0, 1000)

		return self



@app.route("/")
def index():

	return Document(title="Counter") [
		t.h1() [
			"Counter"
		],
		CounterComponent()
	]


if __name__ == "__main__":
	app.run(debug=True)
