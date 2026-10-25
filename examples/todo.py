import sys

sys.path.append("")

import domino.tags as t
from domino import Domino
from domino.components import Document


app = Domino(__name__)


class TodoList(t.div):


	def __init__(self, *args, **kwargs):

		super().__init__(*args, **kwargs)

		self.items = []


	def render(self):

		self([
			form := t.form() [
				t.input(name="text", placeholder="What needs doing?", autocomplete="off"),
				t.button(type="submit") [
					"Add"
				]
			],
			t.ul()([
				self.item(index, text) for index, text in enumerate(self.items)
			]),
			t.p() [
				f"{len(self.items)} item(s)"
			]
		])

		form.bind("submit", self.add)


	def item(self, index, text):

		done = t.input(type="checkbox")
		done.bind("change", lambda event: self.remove(index))

		return t.li() [
			done,
			f" {text}"
		]


	def add(self, event):

		text = event.form.get("text", "").strip()
		if text:
			self.items.append(text)

		return self


	def remove(self, index):

		del self.items[index]

		return self


@app.route("/")
def index():

	return Document(title="Todo") [
		t.h1() [
			"Todo"
		],
		TodoList()
	]


if __name__ == "__main__":
	app.run(debug=True)
