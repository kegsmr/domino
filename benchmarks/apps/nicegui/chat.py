from nicegui import ui


# The last 50 messages, shared by every tab of this server process
messages = []


def post(name, text):
	messages.append((name, text))
	del messages[:-50]
	chat_messages.refresh()


# Defined at module level, so refresh() re-renders it in every open tab
@ui.refreshable
def chat_messages():
	for name, text in messages:
		ui.chat_message(text, name=name)


@ui.page("/chat")
def chat():

	def send():
		if text.value.strip():
			post("me", text.value.strip()[:500])
			text.value = ""

	with ui.column().props("id=messages"):
		chat_messages()
	with ui.row():
		text = ui.input(placeholder="Message").props("id=text autocomplete=off").on("keydown.enter", send)
		ui.button("Send", on_click=send).props("id=send")
