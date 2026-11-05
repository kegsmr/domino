from nicegui import ui


# In memory, shared by every tab of this server process
todos = [{"text": f"Todo item {number}", "done": False} for number in range(1000)]


@ui.page("/todo")
def todo():

	def summary():
		return f"{sum(item['done'] for item in todos)} of {len(todos)} done"

	def toggle(item, done):
		item["done"] = done
		status.text = summary()

	def show(item):
		ui.checkbox(item["text"], value=item["done"], on_change=lambda event: toggle(item, event.value))

	def add():
		if text.value.strip():
			item = {"text": text.value.strip(), "done": False}
			todos.append(item)
			with items:
				show(item)
			text.value = ""
			status.text = summary()

	with ui.row():
		text = ui.input(placeholder="What needs doing?").props("id=new autocomplete=off").on("keydown.enter", add)
		ui.button("Add", on_click=add).props("id=add")
	status = ui.label(summary()).props("id=summary")
	with ui.column().props("id=todos") as items:
		for item in todos:
			show(item)
