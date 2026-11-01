# Tests for pages/index.py, run with `pytest`. `page` is that page, open in a simulated browser;
# each test gets an empty database, on a MongoDB started for the tests


def sign_up(page, name):

	page.load("/signup?next=/")
	page.fill("input[name=name]", name)
	page.fill("input[name=email]", f"{name.lower()}@example.com")
	page.fill("input[name=password]", "correct horse battery")
	page.click("button", text="Sign up")


def test_visitors_are_asked_to_log_in(page):

	assert page.text("main p") == "Log in to add tasks."
	assert page.find_all("main form") == []


def test_add_and_finish_a_task(page):

	sign_up(page, "Ada")

	# Back on the task list, signed in
	assert page.path == "/"
	page.fill("input[name=text]", "Buy milk")
	page.click("button", text="Add")

	assert page.text("main li") == "Buy milk Ada"
	assert page.value("input[name=text]") == ""

	page.check("li input[type=checkbox]")
	page.click("button", text="Clear done")

	assert page.find_all("main li") == []


def test_other_tabs_see_new_tasks(page, open_page):

	other = open_page()

	sign_up(page, "Grace")
	page.fill("input[name=text]", "Write tests")
	page.click("button", text="Add")
	# Applies what the server pushed to the other tab
	other.sync()

	assert other.text("main li") == "Write tests Grace"
