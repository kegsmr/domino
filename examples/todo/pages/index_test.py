def test_adding_and_checking_off_items(page):

	page.fill("input[name=text]", "Buy milk")
	page.click("button", text="Add")
	page.fill("input[name=text]", "Walk the dog")
	page.click("button", text="Add")

	assert [item.text for item in page.find_all("li")] == ["Buy milk", "Walk the dog"]
	assert page.text("p") == "2 item(s)"
	# The form was handled by the server, so the input is empty again
	assert page.value("input[name=text]") == ""

	page.click("li input[type=checkbox]")

	assert [item.text for item in page.find_all("li")] == ["Walk the dog"]


def test_blank_items_are_ignored(page):

	page.fill("input[name=text]", "   ")
	page.click("button", text="Add")

	assert page.find_all("li") == []
