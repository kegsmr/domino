import datetime

import flask
import pytest

import domino.tags as t
from domino import Domino, State, forms
from domino.components import Document


def render(element):

	return element._render(indent="")


def app_with(component):
	"""An app whose page at / shows a new `component()`, opened in a simulated browser."""

	app = Domino(__name__, pages=False)
	app.testing = True

	@app.route("/")
	def index():
		return Document() [component()]

	return app.test_page("/")


def field_of(form, name):
	"""A simulated page's form field by name."""

	return form.find(f"form [name={name}]")


class Signup(forms.Form):

	name = forms.Text("Name", required=True, max_length=50)
	email = forms.Email("Email", required=True)
	age = forms.Integer("Age", min=13, max=120)
	plan = forms.Choice(["Hobby", "Pro", "Team"], default="Hobby")
	newsletter = forms.Checkbox("Send me news")
	password = forms.Password(min_length=8)

	received = []


	def submitted(self, data):

		self.received.append(data)


# Field types and coercion


def test_fields_are_collected_in_declaration_order():

	assert list(Signup._fields) == ["name", "email", "age", "plan", "newsletter", "password"]
	assert [field.name for field in Signup().fields] == list(Signup._fields)


def test_subclasses_inherit_fields_and_can_remove_them():

	class More(Signup):
		phone = forms.Text()
		password = None

	assert list(More._fields) == ["name", "email", "age", "plan", "newsletter", "phone"]


def test_a_field_cannot_shadow_what_a_form_uses():

	with pytest.raises(TypeError, match="'errors'"):
		class Bad(forms.Form):
			errors = forms.Text()


def test_values_are_typed():

	class Everything(forms.Form):
		text = forms.Text()
		count = forms.Integer()
		ratio = forms.Float()
		day = forms.Date()
		ok = forms.Checkbox()
		size = forms.Choice([(1, "Small"), (2, "Large")])
		notes = forms.TextArea()

	data, errors = Everything.validate_data({
		"text": "  hi  ", "count": "42", "ratio": "0.5", "day": "2024-02-29", "ok": "on", "size": "2", "notes": "a\nb"
	})

	assert errors == {}
	assert data == {
		"text": "hi", "count": 42, "ratio": 0.5, "day": datetime.date(2024, 2, 29), "ok": True, "size": 2, "notes": "a\nb"
	}
	assert data.count == 42 and data.size == 2


def test_empty_values():

	class Empty(forms.Form):
		text = forms.Text()
		count = forms.Integer()
		ok = forms.Checkbox()
		size = forms.Choice(["S", "L"])

	data, errors = Empty.validate_data({"text": "", "count": "  ", "size": ""})

	assert errors == {}
	assert data == {"text": "", "count": None, "ok": False, "size": None}


def test_bad_values_of_each_type():

	class Typed(forms.Form):
		count = forms.Integer()
		ratio = forms.Float()
		day = forms.Date()
		size = forms.Choice(["S", "L"])

	_, errors = Typed.validate_data({"count": "1.5", "ratio": "nan", "day": "2023-02-30", "size": "XL"})

	assert errors == {
		"count": "Enter a whole number.",
		"ratio": "Enter a number.",
		"day": "Enter a valid date.",
		"size": "Choose one of the options.",
	}


def test_integer_accepts_what_number_inputs_send():

	class Typed(forms.Form):
		count = forms.Integer()

	assert Typed.validate_data({"count": "1e3"})[0].count == 1000
	assert Typed.validate_data({"count": "4.0"})[0].count == 4


def test_repeated_names_use_the_last_value():

	assert Signup.validate_data({"name": ["a", "b"], "email": "a@b.co"})[0].name == "b"


# Built-in checks


def test_required():

	_, errors = Signup.validate_data({"name": "   ", "email": ""})

	assert errors == {"name": "This field is required.", "email": "This field is required."}


def test_required_checkbox_must_be_checked():

	class Terms(forms.Form):
		agree = forms.Checkbox(required=True)

	assert Terms.validate_data({})[1] == {"agree": "Check this box to continue."}
	assert Terms.validate_data({"agree": "on"}) == ({"agree": True}, {})


def test_min_and_max():

	base = {"name": "Ada", "email": "a@b.co"}

	assert Signup.validate_data(dict(base, age="12"))[1] == {"age": "Must be at least 13."}
	assert Signup.validate_data(dict(base, age="121"))[1] == {"age": "Must be at most 120."}
	assert Signup.validate_data(dict(base, age="13"))[1] == {}


def test_date_limits():

	class Booking(forms.Form):
		day = forms.Date(min="2024-01-01", max=datetime.date(2024, 12, 31))

	assert Booking.validate_data({"day": "2023-12-31"})[1] == {"day": "Must be on or after 2024-01-01."}
	assert Booking.validate_data({"day": "2025-01-01"})[1] == {"day": "Must be on or before 2024-12-31."}


def test_lengths():

	base = {"name": "Ada", "email": "a@b.co"}

	assert Signup.validate_data(dict(base, name="x" * 51))[1] == {"name": "Use at most 50 characters."}
	assert Signup.validate_data(dict(base, password="short"))[1] == {"password": "Use at least 8 characters."}
	# Passwords aren't stripped
	assert Signup.validate_data(dict(base, password="  pass  "))[0].password == "  pass  "


def test_pattern_matches_the_whole_value():

	class Code(forms.Form):
		code = forms.Text(pattern="[A-Z]{3}")

	assert Code.validate_data({"code": "ABC"})[1] == {}
	assert Code.validate_data({"code": "ABCD"})[1] == {"code": "Enter a value in the expected format."}


def test_email():

	for good in ["ada@example.com", "a.b+c@mail.example.co.uk"]:
		assert Signup.validate_data({"name": "Ada", "email": good})[1] == {}, good

	# "a@b" passes the browser's check, but not the server's
	for bad in ["ada", "ada@", "@example.com", "a@b", "a b@example.com"]:
		assert Signup.validate_data({"name": "Ada", "email": bad})[1] == {"email": "Enter a valid email address."}, bad


def test_messages_can_be_changed():

	class Short(forms.Form):
		name = forms.Text(required=True, messages={"required": "Who are you?"})

	assert Short.validate_data({})[1] == {"name": "Who are you?"}


# Custom checks


def test_validators():

	def even(value):
		if value % 2:
			return "Must be even."

	def not_seven(value):
		if value == 7:
			raise forms.ValidationError("Not 7.")

	class Numbers(forms.Form):
		count = forms.Integer(validators=[even, not_seven])

	assert Numbers.validate_data({"count": "3"})[1] == {"count": "Must be even."}
	assert Numbers.validate_data({"count": "4"}) == ({"count": 4}, {})
	# Validators only see values that are there, and typed ones
	assert Numbers.validate_data({"count": ""}) == ({"count": None}, {})


def test_validate_field_methods():

	class Unique(forms.Form):
		username = forms.Text()

		def validate_username(self, value):
			if value == "admin":
				return "That name is taken."

	assert Unique.validate_data({"username": "admin"})[1] == {"username": "That name is taken."}
	assert Unique.validate_data({"username": "ada"})[1] == {}


def test_cross_field_validate():

	class Passwords(forms.Form):
		password = forms.Password(required=True)
		confirm = forms.Password(required=True)

		def validate(self, data):
			if data.password != data.confirm:
				raise forms.ValidationError("The passwords don't match.", field="confirm")

	assert Passwords.validate_data({"password": "a", "confirm": "b"})[1] == {"confirm": "The passwords don't match."}
	assert Passwords.validate_data({"password": "a", "confirm": "a"})[1] == {}
	# Only once every field is valid
	assert Passwords.validate_data({"password": "a"})[1] == {"confirm": "This field is required."}


def test_validate_can_report_form_errors_and_call_error():

	class Booking(forms.Form):
		start = forms.Integer()
		end = forms.Integer()

		def validate(self, data):
			if data.end < data.start:
				self.error("end", "Must be after the start.")
				return "Check the dates."

	assert Booking.validate_data({"start": "5", "end": "1"})[1] == {"end": "Must be after the start.", None: "Check the dates."}


# Rendering


def test_html_constraint_attributes():

	html = render(Signup())

	assert 'name="name" value="" type="text" required maxlength="50"' in html
	assert 'name="email" value="" type="email" required' in html
	assert 'type="number" min="13" max="120"' in html
	assert 'type="password" minlength="8"' in html
	assert '<option value="Hobby" selected>' in html
	assert 'name="newsletter" type="checkbox">' in html
	assert '<button type="submit">Submit</button>' in html

	class Others(forms.Form):
		code = forms.Text(pattern="[A-Z]{3}", placeholder="ABC")
		ratio = forms.Float(min=0)
		day = forms.Date(min="2024-01-01")
		size = forms.Choice(["S", "L"], required=True)
		notes = forms.TextArea(max_length=500)

	html = render(Others())

	assert 'pattern="[A-Z]{3}"' in html and 'placeholder="ABC"' in html
	assert 'type="number" min="0" step="any"' in html
	assert 'type="date" min="2024-01-01"' in html
	assert '<select id="' in html and 'name="size" required>' in html
	assert '<option value="" selected>Choose…</option>' in html
	assert 'name="notes" maxlength="500">' in html


def test_labels_point_at_their_inputs():

	form = Signup()
	html = render(form)

	assert f'<label for="{form.id()}-email">Email</label>' in html
	assert f'<input id="{form.id()}-email" name="email"' in html
	# Labels default to the field's name
	assert f'<label for="{form.id()}-password">Password</label>' in html


def test_help_text_describes_the_input():

	class Help(forms.Form):
		password = forms.Password(help="At least 8 characters.")

	form = Help()
	html = render(form)

	assert f'aria-describedby="{form.id()}-password-help"' in html
	assert f'<small class="help" id="{form.id()}-password-help">At least 8 characters.</small>' in html


def test_extra_attributes_reach_the_input():

	class Login(forms.Form):
		email = forms.Email(autocomplete="email")

	assert 'autocomplete="email"' in render(Login())


def test_errors_render_with_aria_attributes():

	form = Signup()
	form.error("email", "Already taken")
	form.error(None, "Try again later")
	html = render(form)

	assert f'aria-invalid="true" aria-describedby="{form.id()}-email-error"' in html
	assert f'<p class="error" id="{form.id()}-email-error" role="alert">Already taken</p>' in html
	assert '<p class="form-error" role="alert">Try again later</p>' in html
	assert html.count('aria-invalid="true"') == 1


def test_escaping_of_labels_values_and_errors():

	class Risky(forms.Form):
		name = forms.Text("<b>Name</b>", help="<i>help</i>")
		size = forms.Choice([("<x>", "<Big>")])

	form = Risky(initial={"name": '"><script>alert(1)</script>'})
	form.error("name", "<img src=x onerror=alert(1)>")
	html = render(form)

	assert "<script>alert" not in html and "<b>" not in html and "<i>" not in html and "<img" not in html
	assert "&lt;b&gt;Name&lt;/b&gt;" in html
	assert 'value="&#34;&gt;&lt;script&gt;alert(1)&lt;/script&gt;"' in html
	assert "&lt;img src=x onerror=alert(1)&gt;" in html
	assert '<option value="&lt;x&gt;">&lt;Big&gt;</option>' in html


def test_initial_values_and_submit_text():

	class Profile(forms.Form):
		name = forms.Text()
		day = forms.Date()
		ok = forms.Checkbox(default=True)

		submit_text = "Save"

	html = render(Profile(initial={"name": "Ada", "day": datetime.date(1815, 12, 10)}))

	assert 'name="name" value="Ada"' in html
	assert 'value="1815-12-10"' in html
	assert 'type="checkbox" checked' in html or 'checked type="checkbox"' in html
	assert ">Save</button>" in html
	# A setting, not an HTML attribute
	assert "submit-text" not in html
	assert ">Go</button>" in render(Profile(submit_text="Go"))


def test_rendering_a_field_yourself():

	class Custom(forms.Form):
		email = forms.Email("Email", required=True)

		def render(self):
			email = self.fields.email
			return [
				t.div(class_="row") [
					email.label("Your email"),
					email.input(placeholder="you@example.com"),
				],
				email.error(),
				t.button() ["Go"],
			]

	page = app_with(Custom)
	label = page.find(".row label")

	assert label.text == "Your email"
	assert label.attrs["for"] == page.find(".row input").attrs["id"]
	assert page.find("input").attrs["placeholder"] == "you@example.com"
	assert page.find_all("[role=alert]") == []

	page.click("button")

	assert page.text("[role=alert]") == "This field is required."
	assert page.find("input").attrs["aria-invalid"] == "true"


def test_fields_by_name():

	form = Signup()

	assert form.fields["email"].name == "email"
	assert len(form.fields) == 6
	with pytest.raises(AttributeError):
		form.fields.nope
	with pytest.raises(KeyError):
		form.fields["nope"]


def test_default_styles_are_scoped_to_forms():

	page = app_with(Signup)

	assert ".Form .field {" in page.html
	assert ".Form select[aria-invalid=true]" in page.html
	assert 'class="Signup Form"' in page.html


# Submitting


def test_typed_data_is_passed_to_submitted():

	Signup.received.clear()
	page = app_with(Signup)
	page.fill("input[name=name]", "Ada").fill("input[name=email]", "ada@example.com").fill("input[name=age]", "36")
	page.select("select[name=plan]", "Pro")
	page.check("input[name=newsletter]")
	page.click("button")

	assert Signup.received == [{
		"name": "Ada", "email": "ada@example.com", "age": 36, "plan": "Pro", "newsletter": True, "password": ""
	}]
	assert isinstance(Signup.received[0], forms.Data)


def test_invalid_submit_keeps_values_and_does_not_call_submitted():

	Signup.received.clear()
	page = app_with(Signup)
	page.fill("input[name=name]", "Ada").fill("input[name=email]", "nope").fill("input[name=age]", "12")
	page.fill("input[name=password]", "secret password")
	page.select("select[name=plan]", "Team")
	page.check("input[name=newsletter]")
	page.click("button")

	assert Signup.received == []
	assert [alert.text for alert in page.find_all("[role=alert]")] == ["Enter a valid email address.", "Must be at least 13."]
	assert page.value("input[name=name]") == "Ada"
	assert page.value("input[name=email]") == "nope"
	assert page.value("input[name=age]") == "12"
	assert page.value("select[name=plan]") == "Team"
	assert page.value("input[name=newsletter]") is True
	# Not rendered back into the page
	assert page.value("input[name=password]") == ""
	assert "secret password" not in page.html


def test_form_resets_after_success():

	page = app_with(Signup)
	page.click("button")
	assert len(page.find_all("[role=alert]")) == 2

	page.fill("input[name=name]", "Ada").fill("input[name=email]", "ada@example.com")
	page.check("input[name=newsletter]")
	page.click("button")

	assert page.find_all("[role=alert]") == []
	assert page.value("input[name=name]") == ""
	assert page.value("input[name=email]") == ""
	assert page.value("input[name=newsletter]") is False


def test_error_from_submitted_keeps_the_form_filled():

	class Register(forms.Form):
		email = forms.Email(required=True)
		done = State(False)

		def submitted(self, data):
			if data.email == "taken@example.com":
				self.error("email", "Already taken")
				return
			self.done = True

	page = app_with(Register)
	page.fill("input[name=email]", "taken@example.com")
	page.click("button")

	assert page.text("[role=alert]") == "Already taken"
	assert page.value("input[name=email]") == "taken@example.com"

	page.fill("input[name=email]", "free@example.com")
	page.click("button")

	assert page.find_all("[role=alert]") == []
	assert page.value("input[name=email]") == ""


def test_submitted_callback_and_reset():

	got = []

	class Note(forms.Form):
		text = forms.Text(required=True)

	class Notes(t.div):

		def render(self):
			return [Note(submitted=got.append)]

	page = app_with(Notes)
	page.fill("input[name=text]", "hello")
	page.click("button")

	assert got == [{"text": "hello"}]

	form = Note()
	form.error("text", "Bad")
	form.reset()

	assert form.errors == {}


def test_submitted_can_change_a_parent_that_then_re_renders():

	class Note(forms.Form):
		text = forms.Text(required=True)

	class Flow(t.div):

		saved = State(None)

		def render(self):
			if self.saved:
				return [t.p() [f"Saved {self.saved}"]]
			return [Note(submitted=self.save)]

		def save(self, data):
			self.saved = data.text

	page = app_with(Flow)
	page.fill("input[name=text]", "hello")
	page.click("button")

	assert page.text("p") == "Saved hello"


def test_custom_render_still_submits():

	class Bare(forms.Form):
		text = forms.Text(required=True)

		def render(self):
			return [self.fields.text.input(), t.button() ["Send"]]

	page = app_with(Bare)
	page.click("button")

	assert page.find("input").attrs["aria-invalid"] == "true"


# Live validation


def test_live_validation_on_change():

	class Live(forms.Form):
		email = forms.Email(required=True, live=True)
		name = forms.Text(required=True)

	page = app_with(Live)
	email = field_of(page, "email")

	assert email.attrs["data-event-id"].endswith("-change")

	page.fill("input[name=name]", "Ada")
	page.fill("input[name=email]", "nope")
	page.dispatch(field_of(page, "email"), "change")

	# Only the field that changed is checked
	assert [alert.text for alert in page.find_all("[role=alert]")] == ["Enter a valid email address."]
	assert page.value("input[name=email]") == "nope"
	assert page.value("input[name=name]") == "Ada"

	page.fill("input[name=email]", "ada@example.com")
	page.dispatch(field_of(page, "email"), "change")

	assert page.find_all("[role=alert]") == []


def test_live_validation_keeps_other_fields_errors():

	class Live(forms.Form):
		email = forms.Email(required=True, live=True)
		name = forms.Text(required=True)

	page = app_with(Live)
	page.click("button")
	assert len(page.find_all("[role=alert]")) == 2

	page.fill("input[name=email]", "ada@example.com")
	page.dispatch(field_of(page, "email"), "change")

	assert [alert.text for alert in page.find_all("[role=alert]")] == ["This field is required."]
	assert "aria-invalid" in field_of(page, "name").attrs


def test_live_validation_while_typing_is_debounced():

	class Live(forms.Form):
		username = forms.Text(min_length=3, live="input", debounce=200)
		nickname = forms.Text(live="blur")

		def validate_username(self, value):
			if value == "admin":
				return "Taken."

	html = render(Live())

	assert 'data-debounce-input="200"' in html
	assert html.count("-blur") == 1

	page = app_with(Live)
	page.type("input[name=username]", "admin")

	assert page.text("[role=alert]") == "Taken."


def test_validate_data_in_any_handler():

	results = []

	class Plain(t.form):

		def render(self):
			self.bind("submit", self.save)
			return [t.input(name="name"), t.input(name="email"), t.button() ["Go"]]

		def save(self, event):
			results.append(Signup.validate_data(event.form))

	page = app_with(Plain)
	page.fill("input[name=name]", "Ada").fill("input[name=email]", "bad")
	page.click("button")

	data, errors = results[0]
	assert errors == {"email": "Enter a valid email address."}
	assert data.name == "Ada"


def test_validate_data_takes_a_flask_request_form():

	app = Domino(__name__, pages=False)

	@app.route("/signup", methods=["POST"])
	def signup():
		data, errors = Signup.validate_data(flask.request.form)
		return {"age": data.get("age"), "newsletter": data.get("newsletter"), "errors": errors}

	response = app.test_client().post("/signup", data={"name": "Ada", "email": "ada@example.com", "age": "36", "newsletter": "on"})

	assert response.get_json() == {"age": 36, "newsletter": True, "errors": {}}
