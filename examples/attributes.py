import sys

sys.path.append("")

import domino.tags as t
from domino import Domino
from domino.components import Document
from domino.bootstrap import BootstrapCSS, container, py_5


app = Domino(__name__)


class Page(t.main, container, py_5):
	pass


class Settings(t.div):


	def __init__(self, *args, **kwargs):

		super().__init__(*args, **kwargs)

		self.notifications = False
		self.saved = False


	def render(self):

		# class_ adds plain CSS classes (here Bootstrap's), for_ avoids the Python keyword,
		# and aria_*/data_* become aria-*/data-*
		state = "off"
		toggle_class = "btn-outline-secondary"
		if self.notifications:
			state = "on"
			toggle_class = "btn-success"

		self([
			t.div(class_="card shadow-sm", style={"max_width": "28rem"}) [
				t.div(class_="card-body") [
					t.h5(class_="card-title") [
						"Settings"
					],
					t.label(for_="display-name") [
						"Display name"
					],
					t.input(id="display-name", class_="form-control mb-3", value="Ada"),
					(toggle := t.button(
						type="button",
						class_=["btn", toggle_class, "mr-2"],
						aria_pressed=str(self.notifications).lower(),
						data_state=state,
					) [
						f"Notifications: {state}"
					]),
					(save := t.button(type="button", class_="btn btn-primary") [
						"Save"
					]),
					self.message()
				]
			]
		])

		toggle.bind("click", self.toggle)
		save.bind("click", self.save)


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

		return self


	def save(self):

		self.saved = True

		return self


@app.route("/")
def index():

	page = Document(title="Classes and attributes") [
		Page() [
			t.h1(class_="h3 mb-4") [
				"Classes and attributes"
			],
			Settings()
		]
	]

	page.head.add_children([BootstrapCSS()])

	return page


if __name__ == "__main__":
	app.run(debug=True)
