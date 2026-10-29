import content


def test_lists_every_topic(page):

	assert [link.attrs["href"] for link in page.find_all(".Topics a")] == [f"/guide/{topic.slug}" for topic in content.GUIDE]
	assert page.find("title").text == "Guide · Domino"
