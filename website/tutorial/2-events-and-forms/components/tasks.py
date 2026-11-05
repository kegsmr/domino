from domino import Component, State
import domino.tags as t


class Tasks(Component):

	# A list of dicts now: each task knows whether it's done
	items = State([
		{"text": "Read the tutorial", "done": True},
		{"text": "Build something", "done": False},
	])


	def render(self):

		left = len([item for item in self.items if not item["done"]])

		return [
			# Submitting runs add() on the server; the page doesn't reload
			t.form(on_submit=self.add) [
				t.input(name="text", placeholder="What needs doing?", required=True, autocomplete="off"),
				t.button(type="submit") [
					"Add"
				]
			],
			t.ul [[
				t.li [
					t.label [
						# (handler, argument): a change calls self.toggle(index), with this checkbox's index
						t.input(type="checkbox", checked=item["done"], on_change=(self.toggle, index)),
						f" {item['text']}"
					]
				]
				for index, item in enumerate(self.items)
			]],
			t.p [
				f"{left} left ",
				t.button(type="button", on_click=self.clear) [
					"Clear done"
				]
			]
		]


	# A handler that takes an argument gets the Event: event.form has the form's fields
	def add(self, event):

		text = event.form["text"].strip()
		if text:
			self.items = self.items + [{"text": text[:200], "done": False}]


	def toggle(self, index):

		item = self.items[index]
		self.items = self.items[:index] + [dict(item, done=not item["done"])] + self.items[index + 1:]


	def clear(self):

		self.items = [item for item in self.items if not item["done"]]
