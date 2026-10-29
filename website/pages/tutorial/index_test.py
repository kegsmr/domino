import content


def test_lists_the_steps_in_order(page):

	links = page.find_all(".Steps a")

	assert [link.attrs["href"] for link in links] == [f"/tutorial/{step.slug}" for step in content.STEPS]
	assert page.find(".Steps strong").text == "Your first page"
	assert page.find(".Sidebar a[aria-current=page]").text == "Introduction"
	assert len(content.STEPS) == 8
