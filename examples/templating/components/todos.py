import domino.tags as t
from domino import Component, State


# The todo list: markup in todos.html, Python for logic. Todos has a render() because it only
# composes: it decides which components to show and hands them data and its own handlers
class Todos(Component):

	items = State([
		{"text": "Write the markup in HTML", "done": True},
		{"text": "Keep the logic in Python", "done": False},
	])


	def render(self):

		if not self.items:
			return [TodoForm(on_add=self.add), EmptyState()]

		return [
			TodoForm(on_add=self.add),
			TodoList(items=self.items, on_toggle=self.toggle, on_remove=self.remove),
		]


	def add(self, text):

		self.items = self.items + [{"text": text, "done": False}]


	def toggle(self, index):

		items = list(self.items)
		items[index] = dict(items[index], done=not items[index]["done"])
		self.items = items


	def remove(self, index):

		self.items = self.items[:index] + self.items[index + 1:]


class TodoForm(t.form):

	# on_add = None declares a prop: the parent's handler, called with the text
	on_add = None


	def submit(self, event):

		text = event.form.get("text", "").strip()
		if text:
			self.on_add(text[:200])


class TodoList(Component):

	# Props, set by the parent: TodoList(items=..., on_toggle=..., on_remove=...)
	items = None
	on_toggle = None
	on_remove = None


	def remaining(self):

		return sum(1 for item in self.items if not item["done"])


	def item_class(self, item):

		return {"done": item["done"]}


class EmptyState(Component):

	pass
