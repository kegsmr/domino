from nicegui import ui


@ui.page("/counter")
def counter():
	count = {"value": 0}

	def increment():
		count["value"] += 1
		label.text = str(count["value"])

	ui.button("+1", on_click=increment).props("id=inc")
	label = ui.label("0").props("id=count")
