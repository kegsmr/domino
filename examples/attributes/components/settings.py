import domino.tags as t
from domino import State


class Settings(t.div):

	notifications = State(False)
	saved = State(False)


	def render(self):

		# class_ adds plain CSS classes (here Bootstrap's), for_ avoids the Python keyword,
		# and aria_*/data_* become aria-*/data-*
		state = "off"
		toggle_class = "btn-outline-secondary"
		if self.notifications:
			state = "on"
			toggle_class = "btn-success"

		return [
			t.div(class_="card shadow-sm", style={"max_width": "28rem"}) [
				t.div(class_="card-body") [
					t.h5(class_="card-title") [
						"Settings"
					],
					t.label(for_="display-name") [
						"Display name"
					],
					t.input(id="display-name", class_="form-control mb-3", value="Ada"),
					t.button(
						type="button",
						class_=["btn", toggle_class, "mr-2"],
						aria_pressed=str(self.notifications).lower(),
						data_state=state,
						on_click=self.toggle,
					) [
						f"Notifications: {state}"
					],
					t.button(type="button", class_="btn btn-primary", on_click=self.save) [
						"Save"
					],
					self.message()
				]
			]
		]


	def message(self):

		if not self.saved:
			return t.p(class_="text-muted small mt-3 mb-0") [
				"Changes aren't saved yet."
			]

		return t.div(class_="alert alert-success mt-3 mb-0", role="status") [
			"Saved!"
		]


	def toggle(self):

		self.notifications = not self.notifications
		self.saved = False


	def save(self):

		self.saved = True
