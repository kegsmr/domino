# Tests for pages/index.py: `page` is that page, open in a simulated browser. Run with `pytest`


def test_starts_at_zero(page):

	assert page.text("p") == "Current Count: 0"


def test_buttons_change_the_count(page):

	page.click("button", text="Increment")
	page.click("button", text="Increment")
	page.click("button", text="Decrement")

	assert page.text("p") == "Current Count: 1"


def test_each_visitor_has_their_own_count(open_page):

	first = open_page()
	second = open_page()

	first.click("button", text="Increment")

	assert first.text("p") == "Current Count: 1"
	assert second.text("p") == "Current Count: 0"
