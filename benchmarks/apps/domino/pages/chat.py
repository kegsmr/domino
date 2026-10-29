import domino.tags as t

from data import messages, post


class Page(t.div):


	def render(self):

		recent = messages.find(sort=[("sent", -1)], limit=50).fetch()

		return [
			t.ul(id="messages")([
				t.li() [
					t.strong() [
						message["name"]
					],
					f" {message['text']}"
				]
				for message in reversed(recent)
			]),
			t.form(on_submit=self.send) [
				t.input(id="text", name="text", placeholder="Message", autocomplete="off"),
				t.button(id="send", type="submit") [
					"Send"
				]
			]
		]


	def send(self, event):

		text = event.form.get("text", "").strip()
		if text:
			post("me", text)
