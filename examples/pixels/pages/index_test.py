# Tests for pages/index.html, run with `pytest`. Each test gets an empty database, on a MongoDB
# started for the tests


def pixel(page, key):

	return page.find(f"button[data-pixel={key}]")


def test_pressing_a_pixel_paints_it(page):

	assert page.text(".stats") == "0 of 576 pixels painted"

	page.trigger("button[data-pixel=3-4]", "pointerdown")

	assert "#ff595e" in pixel(page, "3-4").attrs["style"]
	assert page.text(".stats") == "1 of 576 pixels painted"


def test_dragging_paints_as_it_goes(page):

	# The browser sends pointerenter only while the button is held down (while-pressed)
	page.trigger("button[data-pixel=0-0]", "pointerdown")
	page.trigger("button[data-pixel=1-0]", "pointerenter")
	page.trigger("button[data-pixel=2-0]", "pointerenter")

	assert page.text(".stats") == "3 of 576 pixels painted"


def test_picking_a_color_paints_with_it(page):

	page.click("button[aria-label='#1982c4']")
	page.trigger("button[data-pixel=0-0]", "pointerdown")

	assert page.find(".Palette button.picked").attrs["aria-label"] == "#1982c4"
	assert "#1982c4" in pixel(page, "0-0").attrs["style"]


def test_everyone_paints_the_same_canvas(open_page):

	ada = open_page()
	grace = open_page()

	ada.trigger("button[data-pixel=5-5]", "pointerdown")
	grace.sync()

	assert "#ff595e" in pixel(grace, "5-5").attrs["style"]
	assert grace.text(".stats") == "1 of 576 pixels painted"

	# Each window has its own brush
	grace.click("button[aria-label='#8ac926']")
	grace.trigger("button[data-pixel=5-5]", "pointerdown")
	ada.sync()

	assert "#8ac926" in pixel(ada, "5-5").attrs["style"]
	assert ada.find(".Palette button.picked").attrs["aria-label"] == "#ff595e"


def test_clear_empties_it_for_everyone(open_page):

	ada = open_page()
	grace = open_page()
	ada.trigger("button[data-pixel=1-1]", "pointerdown")
	ada.click("button", text="Clear")
	grace.sync()

	assert grace.text(".stats") == "0 of 576 pixels painted"
