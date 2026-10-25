import domino.tags as t
from domino import State


class TodoList(t.div):

	items = State([])


	def render(self):

		return [
			t.form(on_submit=self.add) [
				t.input(name="text", placeholder="What needs doing?", autocomplete="off"),
				t.button(type="submit") [
					"Add"
				]
			],
			t.ul()([
				t.li() [
					t.input(type="checkbox", on_change=lambda event, index=index: self.remove(index)),
					f" {text}"
				]
				for index, text in enumerate(self.items)
			]),
			t.p() [
				f"{len(self.items)} item(s)"
			]
		]


	def add(self, event):

		text = event.form.get("text", "").strip()
		if text:
			self.items = self.items + [text]


	def remove(self, index):

		self.items = self.items[:index] + self.items[index + 1:]
