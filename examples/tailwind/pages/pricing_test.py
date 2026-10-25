# Tests for pages/pricing.py, whose component renders components/pricing.html


def test_the_page_links_the_tailwind_css(page):

	assert page.find("head link[data-domino-tailwind]").attrs["href"].startswith("/_domino/tailwind.css")


def test_the_toggle_switches_prices_and_classes(page):

	monthly = lambda: page.find("button", text="Monthly")
	yearly = lambda: page.find("button", text="Yearly")

	assert [price.text for price in page.find_all(".price")] == ["$0", "$19", "$49"]
	assert "bg-white" in monthly().attrs["class"].split()

	page.click("button", text="Yearly")

	assert [price.text for price in page.find_all(".price")] == ["$0", "$182", "$470"]
	assert "bg-white" in yearly().attrs["class"].split()
	assert "bg-white" not in monthly().attrs["class"].split()
	assert yearly().attrs["aria-pressed"] == "true"


def test_the_featured_plan_stands_out(page):

	assert "bg-indigo-600" in page.find("h2", text="Pro").parent.attrs["class"]
