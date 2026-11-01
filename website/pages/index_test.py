# Tests for pages/index.py, the home page, and what every page shares (pages/layout.py)

import content


def test_home_page(page):

	assert page.status == 200
	assert page.text("h1") == "Web apps in Python, live in the browser."
	assert "pip install domino-web" in page.find(".Code", text="domino create").text
	assert page.find(".Sidebar a[aria-current=page]").text == "Overview"


def test_the_example_is_the_component_running_next_to_it(page):

	source = (content.SITE / "components" / "counter.py").read_text(encoding="utf-8")

	assert page.find(".Example .Code figcaption").text.startswith("components/counter.py")
	assert page.text(".Example .Code pre") == " ".join(source.split())

	page.click(".Counter button", text="+")
	page.click(".Counter button", text="+")
	page.click(".Counter button", text="−")

	assert page.text(".Counter output") == "1"


def test_every_sidebar_page_renders_and_is_marked_current(open_page):

	for label, url in content.PAGES:
		tab = open_page(url)
		assert tab.status == 200, url
		assert tab.find(".Sidebar a[aria-current=page]").text == label, url
		assert len(tab.find_all(".Sidebar a[aria-current]")) == 1, url


def test_titles_and_links_to_the_next_page(open_page):

	tutorial = open_page("/tutorial/1-first-page")

	assert tutorial.find("title").text == "Your first page · Domino"
	assert tutorial.find(".Pager a[rel=prev]").attrs["href"] == "/tutorial"
	assert tutorial.find(".Pager a[rel=next]").attrs["href"] == "/tutorial/2-events-and-forms"


def test_unknown_pages_are_404_inside_the_layout(open_page):

	missing = open_page("/no/such/page")

	assert missing.status == 404
	assert missing.text("h1") == "There's no page here"
	assert missing.find_all(".Sidebar") != []


def test_dark_mode_follows_the_system_or_the_theme_button(page):

	css = page.html

	# page.theme(dark=...): the system's preference, and the theme button's choice, which the
	# server reads from the cookie the button sets
	assert "@media (prefers-color-scheme: dark)" in css
	assert ":root[data-theme=dark]" in css
	assert "data-theme" not in page.find("html").attrs

	page.client.set_cookie("theme", "dark")
	page.load("/guide/styles")

	assert page.find("html").attrs["data-theme"] == "dark"
	assert page.find_all("[data-theme-toggle]") != []


def test_the_menu_button_opens_the_sidebar_on_small_screens(page):

	assert page.find(".MenuToggle button").attrs["aria-expanded"] == "false"

	page.click(".MenuToggle button")

	assert page.find(".MenuToggle button").attrs["aria-expanded"] == "true"
	# The sidebar shows while it's open, with CSS alone
	assert ":root:has(.MenuToggle [aria-expanded=true]) .Sidebar" in page.html


def test_code_blocks_are_highlighted_with_a_copy_button(page):

	code = page.find(".Example .Code")

	assert [node for node in code.elements() if node.attrs.get("class") == "k"]
	assert [node for node in code.elements() if "data-copy" in node.attrs]
