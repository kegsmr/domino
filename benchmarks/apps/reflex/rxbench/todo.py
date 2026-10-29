import dataclasses

import reflex as rx


@dataclasses.dataclass
class Item:
	text: str
	done: bool = False


# In memory, shared by every tab of this server process
TODOS = [Item(f"Todo item {number}") for number in range(1000)]


class TodoState(rx.State):
	items: list[Item] = []

	@rx.event
	def load(self):
		self.items = [dataclasses.replace(item) for item in TODOS]

	@rx.event
	def toggle(self, index: int):
		TODOS[index].done = not TODOS[index].done
		self.items[index] = dataclasses.replace(TODOS[index])

	@rx.event
	def add(self, form: dict):
		if text := form.get("text", "").strip():
			TODOS.append(Item(text))
			self.items.append(Item(text))

	@rx.var
	def summary(self) -> str:
		return f"{sum(item.done for item in self.items)} of {len(self.items)} done"


def todo() -> rx.Component:
	return rx.box(
		rx.form(
			rx.input(id="new", name="text", placeholder="What needs doing?", auto_complete=False),
			rx.button("Add", id="add", type="submit"),
			on_submit=TodoState.add,
			reset_on_submit=True,
		),
		rx.text(TodoState.summary, id="summary"),
		rx.list.unordered(
			rx.foreach(
				TodoState.items,
				lambda item, index: rx.list.item(
					rx.checkbox(item.text, checked=item.done, on_change=lambda _: TodoState.toggle(index)),
				),
			),
			id="todos",
		),
	)
