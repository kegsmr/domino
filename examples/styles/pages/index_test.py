def test_each_component_css_is_written_once(page):

	# Three cards, but one <style> in the <head> with the CSS of each component class
	assert len(page.find_all(".Card")) == 3
	(styles,) = page.find_all("head style[data-domino-css]")
	assert styles.attrs["data-domino-css"].split() == ["Pill", "Board", "Card"]


def test_a_new_component_arrives_with_its_css(page):

	page.click("button", text="Add a card")

	# The fourth card is a Highlight, styled by its own class plus Card's
	assert len(page.find_all(".Highlight")) == 1
	assert page.text(".Highlight h3") == "Card 4"
