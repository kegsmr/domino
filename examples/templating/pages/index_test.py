def test_paired_template_counter(page):

	assert page.text(".Counter strong") == "0"
	assert "disabled" in page.find("button", text="Reset").attrs

	page.click("button", text="+1")
	page.click("button", text="+1")

	assert page.text(".Counter strong") == "2"
	assert "disabled" not in page.find("button", text="Reset").attrs

	page.click("button", text="Reset")

	assert page.text(".Counter strong") == "0"


def test_the_jinja_page_is_a_whole_document(page):

	assert page.text("title") == "Templates"
	assert page.find("html").attrs.get("data-domino-page")
	assert page.html.count("<html") == 1
