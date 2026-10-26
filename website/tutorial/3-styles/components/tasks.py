import domino.tags as t
from domino import State


class Tasks(t.div):

	items = State([
		{"text": "Read the tutorial", "done": True},
		{"text": "Build something", "done": False},
	])

	# Scoped to this component (.Tasks form, .Tasks li, ...) and written into the page once,
	# however many times it's shown. The colors are CSS variables the page's theme sets
	css = {
		"max_width": "28rem",
		"form": {"display": "flex", "gap": "0.5rem"},
		"input[name=text]": {"flex": "1", "min_width": "0"},
		"input, button": {"font": "inherit", "padding": "0.45rem 0.75rem", "border_radius": "6px"},
		"input[name=text], button": {"border": "1px solid var(--line)", "background": "var(--surface)", "color": "inherit"},
		"button[type=submit]": {"background": "var(--accent)", "border_color": "var(--accent)", "color": "white"},
		"ul": {"list_style": "none", "padding": 0, "margin": "1rem 0"},
		"li": {"padding": "0.5rem 0", "border_bottom": "1px solid var(--line)"},
		"li.done": {"color": "var(--muted)", "text_decoration": "line-through"},
		"input[type=checkbox]": {"accent_color": "var(--accent)"},
		".footer": {"display": "flex", "justify_content": "space-between", "align_items": "center", "color": "var(--muted)"},
	}


	def render(self):

		left = len([item for item in self.items if not item["done"]])

		return [
			t.form(on_submit=self.add) [
				t.input(name="text", placeholder="What needs doing?", required=True, autocomplete="off"),
				t.button(type="submit") [
					"Add"
				]
			],
			t.ul()([
				# class_ adds classes after the component's own
				t.li(class_="done" if item["done"] else None) [
					t.label() [
						t.input(type="checkbox", checked=item["done"], on_change=lambda event, index=index: self.toggle(index)),
						f" {item['text']}"
					]
				]
				for index, item in enumerate(self.items)
			]),
			t.div(class_="footer") [
				f"{left} left",
				t.button(type="button", on_click=self.clear) [
					"Clear done"
				]
			]
		]


	def add(self, event):

		text = event.form["text"].strip()
		if text:
			self.items = self.items + [{"text": text[:200], "done": False}]


	def toggle(self, index):

		item = self.items[index]
		self.items = self.items[:index] + [dict(item, done=not item["done"])] + self.items[index + 1:]


	def clear(self):

		self.items = [item for item in self.items if not item["done"]]
