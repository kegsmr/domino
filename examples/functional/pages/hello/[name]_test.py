# pages/hello/[name].py has a URL parameter, so open_page() fills it in


def test_greets_whoever_is_in_the_url(open_page):

	page = open_page(name="Ada")

	assert page.path == "/hello/Ada"
	assert page.text("h1") == "Hello, Ada!"


def test_names_are_escaped(open_page):

	page = open_page(name="<b>Eve")

	# Shown as text, not turned into a <b> tag
	assert page.text("h1") == "Hello, <b>Eve!"
	assert page.find_all("h1 b") == []
