import sys

sys.path.append("")

import domino.tags as t
from domino import Domino
from domino.components import Document


app = Domino(__name__)


PLANS = ["Hobby", "Pro", "Team"]


class SeatCount(t.output):


	def __init__(self, *args, **kwargs):

		super().__init__(*args, **kwargs)

		self.seats = 1


	def render(self):

		self([
			f"{self.seats} seat(s)"
		])


class SignupForm(t.div):


	def __init__(self, *args, **kwargs):

		super().__init__(*args, **kwargs)

		self.submitted = None
		self.seat_count = SeatCount()


	def render(self):

		self([
			form := t.form() [
				t.fieldset() [
					t.legend() [
						"Sign up"
					],
					t.label() [
						"Email ",
						t.input(type="email", name="email", required=True)
					],
					t.label() [
						"Plan ",
						t.select(name="plan")([
							t.option(value=plan) [
								plan
							]
							for plan in PLANS
						])
					],
					t.label() [
						"Seats ",
						(seats := t.input(type="range", name="seats", min=1, max=20, value=self.seat_count.seats)),
						" ",
						self.seat_count
					],
					t.label() [
						t.input(type="checkbox", name="newsletter", value="yes"),
						" Send me the newsletter"
					],
					t.button(type="submit") [
						"Sign up"
					]
				]
			],
			self.summary()
		])

		# Each event's value arrives as event.value; the whole form as event.form
		seats.bind("change", self.set_seats)
		form.bind("submit", self.submit)


	def summary(self):

		if not self.submitted:
			return t.p() [
				"Fill in the form and press Sign up."
			]

		return t.dl()([
			item
			for key, value in self.submitted.items()
			for item in (t.dt() [key], t.dd() [str(value)])
		])


	def set_seats(self, event):

		# Only the seat count re-renders, so the rest of the form keeps what was typed
		self.seat_count.seats = int(event.value)

		return self.seat_count


	def submit(self, event):

		# Unchecked checkboxes aren't sent, like a normal form post
		self.submitted = dict(event.form, newsletter=event.form.get("newsletter") == "yes")
		self.seat_count.seats = int(event.form.get("seats", 1))

		return self


@app.route("/")
def index():

	page = Document(title="Forms") [
		t.h1() [
			"Forms"
		],
		SignupForm()
	]

	page.style("body", font_family="system-ui, sans-serif", max_width="32rem", margin="2rem auto")
	page.style("label", display="block", margin="0.75rem 0")
	page.style("fieldset", border="1px solid #ddd", border_radius="8px", padding="1rem 1.5rem")
	page.style("dt", font_weight="600")

	return page


if __name__ == "__main__":
	app.run(debug=True)
