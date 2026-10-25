import domino.tags as t
from domino import State


class TodoItem(t.li):
	"""One item. Its events call TodoList's methods, so they wait for the server (the inspector
	says why)."""


	def __init__(self, todo, toggle, remove):

		self.todo = todo
		self.toggle = toggle
		self.remove_item = remove

		super().__init__()


	def render(self):

		return [
			t.input(type="checkbox", checked=self.todo["done"], on_change=self.toggle),
			f" {self.todo['text']} ",
			t.button(aria_label="Remove", on_click=self.remove_item) [
				"×"
			]
		]


class TodoList(t.section):

	items = State([{"text": "Open the inspector", "done": False}])
	show = State("all")


	def render(self):

		shown = [
			(index, todo) for index, todo in enumerate(self.items)
			if self.show == "all" or todo["done"] == (self.show == "done")
		]

		return [
			t.h2() [
				"Todo"
			],
			t.form(on_submit=self.add) [
				t.input(name="text", placeholder="What needs doing?", autocomplete="off"),
				" ",
				t.button(type="submit") [
					"Add"
				]
			],
			t.p()([
				t.button(on_click=lambda event, name=name: self.filter(name), aria_pressed=str(self.show == name).lower()) [
					name
				]
				for name in ("all", "active", "done")
			]),
			t.ul()([
				TodoItem(todo, lambda index=index: self.toggle(index), lambda index=index: self.remove(index))
				for index, todo in shown
			])
		]


	def add(self, event):

		# Reads the form: predicted with the text the browser fills in
		text = event.form.get("text", "").strip()
		if text:
			self.items = self.items + [{"text": text, "done": False}]


	def filter(self, name):

		self.show = name


	def toggle(self, index):

		items = list(self.items)
		items[index] = dict(items[index], done=not items[index]["done"])
		self.items = items


	def remove(self, index):

		self.items = self.items[:index] + self.items[index + 1:]
