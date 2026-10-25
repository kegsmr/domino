import sys

sys.path.append("")

import domino.tags as t
from domino import Domino, State
from domino.components import Document


app = Domino(__name__)


class CounterComponent(t.div):

	# Per-component state; changing it re-renders the component
	count = State(0)


	def render(self):

		return [
			t.p() [
				f"Current Count: {self.count}"
			],
			t.button(on_click=self.increment) [
				"Increment"
			],
			t.button(on_click=self.decrement) [
				"Decrement"
			]
		]


	def increment(self):

		self.count += 1


	def decrement(self):

		self.count -= 1


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
