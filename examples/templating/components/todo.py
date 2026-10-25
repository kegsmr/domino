# Template strings (t"...") need Python 3.14; app.py only imports this module there
from domino import Component, State, html


class Todo(Component):

	items = State([])


	def render(self):

		return html(t"""
			<form on_submit={self.add}>
				<input name="text" placeholder="What needs doing?" autocomplete="off">
				<button type="submit">Add</button>
			</form>
			<ul>
				{[self.item(index, text) for index, text in enumerate(self.items)]}
			</ul>
			<p>{len(self.items)} item(s)</p>
		""")


	def item(self, index, text):

		return html(t"""
			<li>
				<input type="checkbox" on_change={(lambda: self.remove(index))}>
				{text}
			</li>
		""")


	def add(self, event):

		text = event.form.get("text", "").strip()
		if text:
			self.items = self.items + [text]


	def remove(self, index):

		self.items = self.items[:index] + self.items[index + 1:]
