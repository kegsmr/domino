# Tests for pages/index.py, run with `pytest`. Each test gets an empty database, on a MongoDB
# started for the tests


def test_sending_a_message(page):

	page.fill("input[name=name]", "Ada")
	page.fill("input[name=text]", "Hello!")
	page.click("button", text="Send")

	assert page.text(".messages") == "Ada Hello!"
	# The name is remembered for the next message; the message field is empty again
	assert page.value("input[name=name]") == "Ada"
	assert page.value("input[name=text]") == ""


def test_other_windows_see_new_messages(open_page):

	ada = open_page()
	grace = open_page()

	ada.fill("input[name=name]", "Ada")
	ada.fill("input[name=text]", "Anyone there?")
	ada.click("button", text="Send")
	grace.sync()

	assert grace.text(".messages") == "Ada Anyone there?"

	grace.fill("input[name=name]", "Grace")
	grace.fill("input[name=text]", "Hi Ada")
	grace.click("button", text="Send")
	ada.sync()

	assert [message.text for message in ada.find_all(".messages li")] == ["Ada Anyone there?", "Grace Hi Ada"]
