# Tests for pages/index.py: `page` is that page, open in a simulated browser. Run with `pytest`


def fill_in(page, **values):

	for name, value in values.items():
		page.fill(f"form [name={name}]", value)


def test_empty_required_fields_show_errors_next_to_them(page):

	page.click("button", text="Create account")

	assert page.text(".field [role=alert]") == "This field is required."
	assert page.find("input[name=name]").attrs["aria-invalid"] == "true"
	assert len(page.find_all("[role=alert]")) == 4  # name, email, password, confirm


def test_server_side_errors_keep_what_was_typed(page):

	fill_in(page, name="Ada", email="ada@example.com", age="9", password="analytical", confirm="engine!!")
	page.select("select[name=plan]", "Pro")
	page.click("button", text="Create account")

	assert page.text("form").count("Must be at least 13.") == 1
	assert page.value("input[name=name]") == "Ada"
	assert page.value("input[name=age]") == "9"
	assert page.value("select[name=plan]") == "Pro"
	# Passwords aren't sent back to the page
	assert page.value("input[name=password]") == ""


def test_password_confirmation_is_checked_across_fields(page):

	fill_in(page, name="Ada", email="ada@example.com", password="analytical", confirm="engine!!")
	page.click("button", text="Create account")

	assert "The passwords don't match." in page.find(".field", text="Confirm password").text


def test_taken_email_is_reported_as_soon_as_it_changes(page):

	page.fill("input[name=email]", "taken@example.com")
	page.dispatch(page.find("input[name=email]"), "change")

	assert page.find(".field", text="Email").text == "Email That email is already registered."
	assert page.value("input[name=email]") == "taken@example.com"

	page.fill("input[name=email]", "ada@example.com")
	page.dispatch(page.find("input[name=email]"), "change")

	assert page.find_all("[role=alert]") == []


def test_success_shows_the_typed_values(page):

	fill_in(page, name="Ada", email="ada@example.com", age="36", password="analytical", confirm="analytical")
	page.select("select[name=plan]", "Team")
	page.check("input[name=newsletter]")
	page.click("button", text="Create account")

	assert page.text("h2") == "Welcome, Ada!"
	values = dict(zip([dt.text for dt in page.find_all("dt")], [dd.text for dd in page.find_all("dd")]))
	assert values == {
		"name": "'Ada' (str)",
		"email": "'ada@example.com' (str)",
		"age": "36 (int)",
		"plan": "'Team' (str)",
		"newsletter": "True (bool)",
	}

	page.click("button", text="Start over")

	assert page.value("input[name=name]") == ""


def test_seats_update_only_the_count(page):

	page.fill("input[name=name]", "Ada")
	page.select("input[name=seats]", "7")

	assert page.text("output") == "7 seat(s)"
	assert page.value("input[name=name]") == "Ada"
