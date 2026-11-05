import time

from domino import Component
import domino.tags as t

from data import tasks


class Tasks(Component):

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

		# Reading the collection here subscribes this component: when it changes, every
		# open page showing a Tasks re-renders and gets the update, without a reload
		items = tasks.find(sort=[("created", 1)]).fetch()
		left = len([item for item in items if not item["done"]])

		return [
			t.form(on_submit=self.add) [
				t.input(name="text", placeholder="What needs doing?", required=True, autocomplete="off"),
				t.button(type="submit") [
					"Add"
				]
			],
			t.ul [[
				t.li(class_="done" if item["done"] else None) [
					t.label [
						# A checkbox's event.value is True or False
						t.input(type="checkbox", checked=item["done"], on_change=(self.toggle, item["_id"])),
						f" {item['text']}"
					]
				]
				for item in items
			]],
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
			tasks.insert({"text": text[:200], "done": False, "created": time.time()})


	# Gets the task's id, then the event (event.value: whether the box is ticked)
	def toggle(self, id, event):

		tasks.update({"_id": id}, {"$set": {"done": event.value}})


	def clear(self):

		tasks.remove({"done": True})
