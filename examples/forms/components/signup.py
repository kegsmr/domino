import domino.tags as t
from domino import State, forms


# Pretend these are already registered
TAKEN = {"taken@example.com", "ada@lovelace.org"}


class Signup(forms.Form):

	# Declared once: the labels, inputs, browser checks, server checks and typed values come from these
	name = forms.Text("Name", required=True, max_length=50, autocomplete="name")
	email = forms.Email("Email", required=True, live=True, autocomplete="email")
	age = forms.Integer("Age", min=13, max=120)
	plan = forms.Choice(["Hobby", "Pro", "Team"], default="Hobby")
	newsletter = forms.Checkbox("Send me the newsletter")
	password = forms.Password("Password", required=True, min_length=8, help="At least 8 characters.", autocomplete="new-password")
	confirm = forms.Password("Confirm password", required=True, autocomplete="new-password")

	submit_text = "Create account"


	def validate_email(self, email):

		# Runs on the server: when the field changes (live=True) and on submit
		if email.lower() in TAKEN:
			return "That email is already registered."


	def validate(self, data):

		# Across fields, once each one is valid
		if data.password != data.confirm:
			raise forms.ValidationError("The passwords don't match.", field="confirm")


class Onboarding(t.div):
	"""The sign-up form, then a welcome showing the typed values it handed over."""

	css = {
		"dl": {"display": "grid", "grid_template_columns": "auto 1fr", "gap": ".25rem 1rem"},
		"dt": {"font_weight": "600"},
		"dd": {"margin": 0},
	}

	account = State(None)


	def render(self):

		if self.account is None:
			# submitted= is called with valid data only
			return [
				Signup(submitted=self.signed_up)
			]

		return [
			t.h2() [
				f"Welcome, {self.account['name']}!"
			],
			t.dl() [[
				item
				for key, value in self.account.items()
				for item in (t.dt() [key], t.dd() [f"{value!r} ({type(value).__name__})"])
			]],
			t.button(type="button", on_click=self.start_over) [
				"Start over"
			]
		]


	def signed_up(self, data):

		# Typed already: age is an int (or None), newsletter a bool
		self.account = {key: value for key, value in data.items() if key not in ("password", "confirm")}


	def start_over(self):

		self.account = None
