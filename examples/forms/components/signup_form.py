import domino.tags as t
from domino import State


PLANS = ["Hobby", "Pro", "Team"]


class SeatCount(t.output):


	def init(self):

		self.seats = 1


	def render(self):

		return [
			f"{self.seats} seat(s)"
		]


class SignupForm(t.div):

	# Scoped to this component (.SignupForm label, ...) and added to the page's <head> once
	css = {
		"label": {"display": "block", "margin": "0.75rem 0"},
		"fieldset": {"border": "1px solid #ddd", "border_radius": "8px", "padding": "1rem 1.5rem"},
		"dt": {"font_weight": "600"},
	}

	submitted = State(None)


	def init(self):

		self.seat_count = SeatCount()


	def render(self):

		# Each event's value arrives as event.value; the whole form as event.form
		return [
			t.form(on_submit=self.submit) [
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
						t.input(type="range", name="seats", min=1, max=20, value=self.seat_count.seats, on_change=self.set_seats),
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
		]


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
		self.seat_count.seats = int(event.form.get("seats", 1))
		self.submitted = dict(event.form, newsletter=event.form.get("newsletter") == "yes")
