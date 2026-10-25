import sys
import time

sys.path.append("")

import domino.tags as t
from domino import Collection, Domino
from domino.components import Document


app = Domino(__name__)


# Shared by everyone. Reading it in render() subscribes the component, so every open
# chat re-renders live when a message is inserted, in every browser tab
messages = Collection("messages")


class Chat(t.div):


	def __init__(self, *args, **kwargs):

		super().__init__(*args, **kwargs)

		self.name = ""


	def render(self):

		recent = messages.find(sort=[("sent", -1)], limit=50).fetch()

		self([
			t.ul(class_="messages")([
				t.li() [
					t.strong() [
						message["name"]
					],
					f" {message['text']}"
				]
				for message in reversed(recent)
			]),
			form := t.form() [
				t.input(name="name", placeholder="Name", required=True, autocomplete="off", value=self.name),
				t.input(name="text", placeholder="Message", required=True, autocomplete="off"),
				t.button(type="submit") [
					"Send"
				]
			]
		])

		form.bind("submit", self.send)


	def send(self, event):

		# Remembered per window, so the form keeps the name after sending
		self.name = event.form.get("name", "").strip()[:30] or "anonymous"

		messages.insert({
			"name": self.name,
			"text": event.form.get("text", "").strip()[:500],
			"sent": time.time(),
		})

		return self


@app.route("/")
def index():

	page = Document(title="Chat") [
		t.h1() [
			"Chat"
		],
		t.p() [
			"Open this page in two windows: messages appear in both instantly."
		],
		Chat()
	]

	page.style("body", font_family="system-ui, sans-serif", max_width="32rem", margin="2rem auto")
	page.style(".messages", list_style="none", min_height="12rem", border="1px solid #ddd", border_radius="8px", padding="0.5rem 1rem")
	page.style("form", display="flex", gap="0.5rem")
	page.style("input", font="inherit", padding="0.4rem", min_width="0")
	page.style("input[name=name]", width="7rem")
	page.style("input[name=text]", flex="1")

	return page


if __name__ == "__main__":
	app.run(debug=True, threaded=True)
