import time

import domino.tags as t
from domino import accounts

from data import tasks


class Tasks(t.div):

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
		"small": {"color": "var(--muted)"},
		".footer": {"display": "flex", "justify_content": "space-between", "align_items": "center", "color": "var(--muted)"},
	}


	def render(self):

		# Reactive too: logging in or out re-renders this
		user = accounts.current_user()
		items = tasks.find(sort=[("created", 1)]).fetch()
		left = len([item for item in items if not item["done"]])

		form = t.p() [
			t.a(href="/login?next=/") ["Log in"],
			" to add tasks."
		]
		if user is not None:
			form = t.form(on_submit=self.add) [
				t.input(name="text", placeholder="What needs doing?", required=True, autocomplete="off"),
				t.button(type="submit") [
					"Add"
				]
			]

		return [
			form,
			t.ul()([
				t.li(class_="done" if item["done"] else None) [
					t.label() [
						t.input(type="checkbox", checked=item["done"], disabled=user is None,
							on_change=lambda event, id=item["_id"]: self.toggle(id, event.value)),
						f" {item['text']} ",
						t.small() [
							item["by"]
						]
					]
				]
				for item in items
			]),
			t.div(class_="footer") [
				f"{left} left",
				t.button(type="button", disabled=user is None, on_click=self.clear) [
					"Clear done"
				]
			]
		]


	def add(self, event):

		# The page's signed-in user, not anything the browser sent
		user = accounts.current_user()
		text = event.form["text"].strip()
		if user is not None and text:
			tasks.insert({"text": text[:200], "done": False, "by": user.get("name") or user["email"], "created": time.time()})


	def toggle(self, id, done):

		if accounts.user_id() is not None:
			tasks.update({"_id": id}, {"$set": {"done": done}})


	def clear(self):

		if accounts.user_id() is not None:
			tasks.remove({"done": True})
