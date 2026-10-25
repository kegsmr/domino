# Tests for pages/index.py: `page` is that page, open in a simulated browser. Run with `pytest`


def test_the_page_links_the_tailwind_css(page):

	link = page.find("head link[data-domino-tailwind]")

	assert link.attrs["rel"] == "stylesheet"
	assert link.attrs["href"].startswith("/_domino/tailwind.css")


def test_cards_and_form_are_styled_with_tailwind_classes(page):

	assert len(page.find_all("#features article")) == 6
	assert "lg:grid-cols-3" in page.find("#features .grid").attrs["class"]
	assert "dark:bg-slate-950" in page.find("body").attrs["class"]
	assert "focus:ring-2" in page.find("input[name=email]").attrs["class"]


def test_the_menu_button_toggles_the_mobile_menu(page):

	menu = lambda: page.find("#mobile-menu")

	assert "hidden" in menu().attrs["class"].split()

	page.click("button", text="Menu")

	assert "block" in menu().attrs["class"].split()
	assert page.find("button[aria-label=Menu]").attrs["aria-expanded"] == "true"

	page.click("button", text="Close")

	assert "hidden" in menu().attrs["class"].split()


def test_signing_up_thanks_you(page):

	page.fill("input[name=name]", "Ada")
	page.fill("input[name=email]", "ada@example.com")
	page.click("button", text="Sign up")

	assert page.text("#signup h2") == "Welcome aboard, Ada!"
