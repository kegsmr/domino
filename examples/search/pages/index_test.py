def test_results_follow_what_you_type(page):

	page.type("input[type=search]", "ru")

	assert [item.text for item in page.find_all("li")] == ["Ruby", "Rust"]
	assert page.text("p") == "2 match(es), 1 request(s) sent"
