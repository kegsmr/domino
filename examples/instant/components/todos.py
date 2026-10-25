import time

import domino.tags as t

from data import todos


class Todos(t.div):
	"""Everything it shows is in a collection. Adding, ticking and removing still show at once:
	the server works out what each would show, and the browser fills in what was typed."""

	css = {
		"form": {"display": "flex", "gap": "0.5rem"},
		"input[name=text]": {"flex": "1", "font": "inherit", "padding": "0.3rem"},
		"ul": {"list_style": "none", "padding": 0},
		"li": {"display": "flex", "justify_content": "space-between", "padding": "0.25rem 0", "border_bottom": "1px solid var(--line)"},
		"li.done label": {"text_decoration": "line-through", "color": "var(--muted)"},
		".remove": {"border": 0, "background": "none", "cursor": "pointer", "font_size": "1.1rem"},
	}


	def render(self):

		items = todos.find(sort="added").fetch()
		left = len([todo for todo in items if not todo["done"]])

		return [
			t.form(on_submit=self.add) [
				t.input(name="text", placeholder="What needs doing?", autocomplete="off", aria_label="New todo"),
				t.button(type="submit") [
					"Add"
				]
			],
			t.ul()([
				t.li(class_="done" if todo["done"] else None) [
					t.label() [
						# By _id, so each one is rendered ahead for its own todo
						t.input(type="checkbox", checked=todo["done"], on_change=lambda event, id=todo["_id"]: self.toggle(id)),
						f" {todo['text']}"
					],
					t.button(class_="remove", aria_label=f"Remove {todo['text']}", on_click=lambda event, id=todo["_id"]: self.remove(id)) [
						"×"
					]
				]
				for todo in items
			]),
			t.p(class_="note") [
				f"{left} left"
			]
		]


	def add(self, event):

		text = event.form["text"].strip()
		if text:
			todos.insert({"text": text, "done": False, "added": time.time()})


	def toggle(self, id):

		todo = todos.find_one({"_id": id})
		if todo:
			todos.update({"_id": id}, {"$set": {"done": not todo["done"]}})


	def remove(self, id):

		todos.remove({"_id": id})
