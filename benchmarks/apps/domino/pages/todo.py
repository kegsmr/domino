import domino.tags as t
from domino import Collection


# In memory, shared by every tab of this server process
todos = Collection()
for number in range(1000):
	todos.insert({"n": number, "text": f"Todo item {number}", "done": False})


class Page(t.div):


	def render(self):

		items = todos.find(sort=[("n", 1)]).fetch()
		done = sum(item["done"] for item in items)

		return [
			t.form(on_submit=self.add) [
				t.input(id="new", name="text", placeholder="What needs doing?", autocomplete="off"),
				t.button(id="add", type="submit") [
					"Add"
				]
			],
			t.p(id="summary") [
				f"{done} of {len(items)} done"
			],
			t.ul(id="todos")([
				t.li(class_="done" if item["done"] else None) [
					t.input(type="checkbox", checked=item["done"], on_change=lambda event, id=item["_id"]: self.toggle(id)),
					f" {item['text']}"
				]
				for item in items
			])
		]


	def add(self, event):

		text = event.form.get("text", "").strip()
		if text:
			todos.insert({"n": todos.count(), "text": text, "done": False})


	def toggle(self, id):

		item = todos.find_one({"_id": id})
		todos.update({"_id": id}, {"$set": {"done": not item["done"]}})
