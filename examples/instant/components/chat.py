import time

import domino.tags as t
from domino import State

from data import messages


class Chat(t.div):
	"""Open the page in two windows: messages show at once in the one that sends them, and as
	soon as the server has them in the other."""

	name = State("")

	css = {
		".messages": {"list_style": "none", "min_height": "6rem", "border": "1px solid var(--line)", "border_radius": "8px", "padding": "0.5rem 1rem"},
		"form": {"display": "flex", "gap": "0.5rem", "margin_top": "0.5rem"},
		"input": {"font": "inherit", "padding": "0.3rem", "min_width": "0"},
		"input[name=name]": {"width": "7rem"},
		"input[name=text]": {"flex": "1"},
	}


	def render(self):

		recent = messages.find(sort=[("sent", -1)], limit=20).fetch()

		return [
			t.ul(class_="messages")([
				t.li() [
					t.strong() [
						message["name"]
					],
					f" {message['text']}"
				]
				for message in reversed(recent)
			]),
			t.form(on_submit=self.send) [
				t.input(name="name", placeholder="Name", value=self.name, required=True, autocomplete="off", aria_label="Name"),
				t.input(name="text", placeholder="Message", required=True, autocomplete="off", aria_label="Message"),
				t.button(type="submit") [
					"Send"
				]
			]
		]


	def send(self, event):

		self.name = event.form["name"].strip()[:30]
		messages.insert({
			"name": self.name,
			"text": event.form["text"].strip()[:500],
			"sent": time.time(),
		})
