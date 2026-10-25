import time

import domino.tags as t
from domino import State

# Reading it in render() subscribes the component, so every open chat re-renders live
# when a message is inserted, in every browser tab
from data import messages


class Chat(t.div):

	# Remembered per window, so the form keeps the name after sending
	name = State("")

	# Scoped to this component (.Chat form, ...) and added to the page's <head> once
	css = {
		".messages": {"list_style": "none", "min_height": "12rem", "border": "1px solid #ddd", "border_radius": "8px", "padding": "0.5rem 1rem"},
		"form": {"display": "flex", "gap": "0.5rem"},
		"input": {"font": "inherit", "padding": "0.4rem", "min_width": "0"},
		"input[name=name]": {"width": "7rem"},
		"input[name=text]": {"flex": "1"},
	}


	def render(self):

		recent = messages.find(sort=[("sent", -1)], limit=50).fetch()

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
				t.input(name="name", placeholder="Name", required=True, autocomplete="off", value=self.name),
				t.input(name="text", placeholder="Message", required=True, autocomplete="off"),
				t.button(type="submit") [
					"Send"
				]
			]
		]


	def send(self, event):

		self.name = event.form.get("name", "").strip()[:30] or "anonymous"

		messages.insert({
			"name": self.name,
			"text": event.form.get("text", "").strip()[:500],
			"sent": time.time(),
		})
