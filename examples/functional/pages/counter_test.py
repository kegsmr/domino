def test_counts_clicks_inside_the_layout(page):

	page.click("button", text="Click me")
	page.click("button", text="Click me")

	assert page.text("main p") == "Clicked 2 times"
	assert page.find("nav a[aria-current=page]").text == "Counter"


def test_each_visit_starts_again(open_page):

	first = open_page()
	first.click("button", text="Click me")

	assert open_page().text("main p") == "Clicked 0 times"
