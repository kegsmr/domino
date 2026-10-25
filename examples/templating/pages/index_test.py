# Tests for pages/index.html, a Domino template page with live components inside


def test_the_template_page_is_a_whole_document(page):

	assert page.text("title") == "Templates"
	assert page.find("html").attrs.get("data-domino-page")
	assert page.html.count("<html") == 1
	assert [card.text for card in page.find_all(".card h2")] == ["Counter", "Todo list", "Questions"]


def test_counter(page):

	assert page.text(".counter strong") == "0"
	assert "disabled" in page.find(".counter button", text="Reset").attrs
	assert "Click +1" in page.text(".counter .hint")

	for _ in range(5):
		page.click(".counter button", text="+1")

	assert page.text(".counter strong") == "5"
	assert "disabled" not in page.find(".counter button", text="Reset").attrs
	assert page.text(".counter .hint") == "5 clicks: that's plenty."

	page.click(".counter button", text="Reset")

	assert page.text(".counter strong") == "0"


def test_todos_add_toggle_and_remove(page):

	page.fill("input[name=text]", "Buy <milk>")
	page.click("button", text="Add")

	assert [li.text for li in page.find_all(".TodoList li span")] == ["Write the markup in HTML", "Keep the logic in Python", "Buy <milk>"]
	assert page.text(".TodoList .hint") == "2 left."

	# Each item's checkbox and button act on that item: on-change="on_toggle(index)"
	page.dispatch(page.find_all(".TodoList input[type=checkbox]")[2], "change")
	assert page.text(".TodoList .hint") == "1 left."
	assert "done" in page.find_all(".TodoList li")[2].attrs["class"]

	page.dispatch(page.find_all(".TodoList .remove")[1], "click")

	assert [li.text for li in page.find_all(".TodoList li span")] == ["Write the markup in HTML", "Buy <milk>"]


def test_empty_state_when_everything_is_removed(page):

	while page.find_all(".TodoList .remove"):
		page.dispatch(page.find_all(".TodoList .remove")[0], "click")

	assert page.text(".EmptyState") == "Nothing to do. Add something above!"


def test_faq_opens_one_answer_at_a_time(page):

	assert page.find_all(".faq dd") == []

	page.click(".faq button", text="Where does the logic go?")
	assert page.text(".faq dd") == "In Python: State, helpers the template reads, and event handlers."

	page.click(".faq button", text="Where does the markup go?")
	assert len(page.find_all(".faq dd")) == 1
	assert page.text(".faq dd").startswith("In .html files")


def test_the_jinja_page(open_page):

	page = open_page("/jinja")

	assert page.text("title") == "Jinja templates"
	page.click(".Counter button", text="+1")
	assert page.text(".Counter strong") == "1"
