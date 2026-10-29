import dataclasses

import reflex as rx


@dataclasses.dataclass
class Message:
	name: str
	text: str


class ChatState(rx.SharedState):
	"""Linked to one room on page load, so every tab shares (and is sent) its messages."""

	messages: list[Message] = []

	@rx.event
	async def join(self):
		await self._link_to("room")

	@rx.event
	def send(self, form: dict):
		if text := form.get("text", "").strip():
			self.messages = [*self.messages, Message("me", text[:500])][-50:]


def chat() -> rx.Component:
	return rx.box(
		rx.list.unordered(
			rx.foreach(ChatState.messages, lambda message: rx.list.item(rx.text.strong(message.name), " ", message.text)),
			id="messages",
		),
		rx.form(
			rx.input(id="text", name="text", placeholder="Message", auto_complete=False),
			rx.button("Send", id="send", type="submit"),
			on_submit=ChatState.send,
			reset_on_submit=True,
		),
	)
