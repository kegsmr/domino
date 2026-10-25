# Tests for pages/private.py, run with `pytest`. Each test gets an empty database (no users),
# on a MongoDB started for the tests


def sign_up(page, name, email):

	page.load("/signup?next=/private")
	page.fill("input[name=name]", name)
	page.fill("input[name=email]", email)
	page.fill("input[name=password]", "correct horse battery")
	page.click("button", text="Sign up")


def test_visitors_are_sent_to_log_in(page):

	assert page.path == "/login"
	assert page.find("form button").text == "Log in"


def test_sign_up_add_a_note_and_log_out(page):

	sign_up(page, "Ada", "ada@example.com")

	# Sent back to the private page, signed in
	assert page.path == "/private"
	assert page.text("main p") == "Only you can see these, Ada."

	page.fill("input[name=text]", "Buy milk")
	page.click("button", text="Add")

	assert page.text("main ul") == "Buy milk"

	page.click("button", text="Log out")

	assert page.text("main p").startswith("You've logged out.")

	page.load("/private")

	assert page.path == "/login"


def test_notes_are_private(open_page):

	ada = open_page("/")
	sign_up(ada, "Ada", "ada@example.com")
	ada.fill("input[name=text]", "Ada's secret")
	ada.click("button", text="Add")

	# Another browser, with its own cookies
	grace = open_page("/")
	sign_up(grace, "Grace", "grace@example.com")

	assert grace.text("main p") == "Only you can see these, Grace."
	assert grace.find_all("main li") == []
