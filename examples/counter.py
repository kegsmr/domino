import sys

sys.path.append("")

from domino import Domino
import domino.tags as t


app = Domino(__name__)


class Document(t.html):

	def init(self):

		self([
			t.head() [
				t.title() [
					"Counter"
				]
			],
			body := t.body()
		])

		self.add_children = body.add_children


class CounterComponent(t.div):


	_count = 0


	def init(self):

		self([
			t.p() [
				f"Current Count: {self._count}"
			],
			increment_button := t.button() [
				"Increment"
			],
			decrement_button := t.button() [
				"Decrement"
			]
		])

		increment_button.bind("click", self.increment)
		decrement_button.bind("click", self.decrement)


	def increment(self):

		CounterComponent._count += 1

		return self

	
	def decrement(self):

		CounterComponent._count -= 1

		return self


@app.route("/")
def index():

	return Document() [
		t.h1() [
			"Counter"
		],
		CounterComponent()
	]


if __name__ == "__main__":
	app.run(debug=True)
