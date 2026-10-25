"""The app the wire benchmark serves: python wire_app.py PORT [--no-compression] [--no-patches].

One page per case, each a component of a typical size, and /bump/<case> endpoints that change
data the way another user would, so pages showing it get a push. See bench_wire.py.
"""

import sys
from pathlib import Path

import domino.tags as t
from domino import Collection, Domino, State
from domino.components import Document


app = Domino(__name__, pages=False)
app.config["DOMINO_MAX_PAGES"] = 100000


class Counter(t.div):

	count = State(0)


	def render(self):

		return [
			t.p() [
				f"Count: {self.count}"
			],
			t.button(on_click=self.increment) [
				"+"
			]
		]


	def increment(self):

		self.count += 1


class Todos(t.div):
	"""100 items; each checkbox toggles its item, which changes that one item."""

	done = State([False] * 100)


	def render(self):

		return [
			t.ul()([
				t.li(class_="done" if done else None) [
					t.input(type="checkbox", checked=done, on_change=lambda event, index=index: self.toggle(index)),
					t.span() [
						f"Item number {index}: something that needs doing"
					]
				]
				for index, done in enumerate(self.done)
			]),
			t.p() [
				f"{sum(self.done)} of {len(self.done)} done"
			]
		]


	def toggle(self, index):

		self.done = self.done[:index] + [not self.done[index]] + self.done[index + 1:]


messages = Collection()
for number in range(200):
	messages.insert({"name": f"user{number % 7}", "text": f"Message {number}, saying something", "sent": number})


class Chat(t.div):
	"""The last 200 messages; another user's message is appended (and the oldest drops off)."""


	def render(self):

		return [
			t.ul(class_="messages")([
				t.li() [
					t.strong() [
						message["name"]
					],
					f" {message['text']}"
				]
				for message in reversed(messages.find(sort=[("sent", -1)], limit=200).fetch())
			]),
			t.form() [
				t.input(name="text", placeholder="Message"),
				t.button(type="submit") [
					"Send"
				]
			]
		]


cells = State([[f"r{row}c{column}" for column in range(5)] for row in range(500)])


class Table(t.div):
	"""500 rows of 5 cells; one cell changes."""


	def render(self):

		return [
			t.table() [
				t.tbody()([
					t.tr()([
						t.td() [
							cell
						]
						for cell in row
					])
					for row in cells.value
				])
			]
		]


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples" / "instant"))

from components.stepper import Stepper  # noqa: E402
from components.tabs import Tabs  # noqa: E402


CASES = {
	"counter": Counter,
	"todo": Todos,
	"chat": Chat,
	"table": Table,
	"stepper": Stepper,
	"tabs": Tabs,
}


def view(case):

	def page():
		return Document() [
			CASES[case]()
		]

	page.__name__ = f"page_{case}"
	app.route(f"/{case}")(page)


for name in CASES:
	view(name)


bumps = {"chat": 200, "table": 0}


@app.route("/bump/chat")
def bump_chat():

	number = bumps["chat"] = bumps["chat"] + 1
	messages.insert({"name": f"user{number % 7}", "text": f"Message {number}, saying something", "sent": number})

	return "ok"


@app.route("/bump/table")
def bump_table():

	number = bumps["table"] = bumps["table"] + 1
	rows = [list(row) for row in cells.value]
	rows[(number * 37) % 500][number % 5] = f"changed {number}"
	cells.value = rows

	return "ok"


if __name__ == "__main__":
	import uvicorn

	port = int(sys.argv[1])
	if "--no-patches" in sys.argv:
		app.config["DOMINO_PATCHES"] = False
	uvicorn.run(app.asgi, host="127.0.0.1", port=port, log_level="warning", backlog=4096,
		ws_per_message_deflate="--no-compression" not in sys.argv)
