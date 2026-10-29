# Tests for pages/guide/[topic].py: the guide is docs/guide/*.md, every page and section

import content
import markup


def test_every_topic_renders_its_sections(open_page):

	for topic in content.GUIDE:
		page = open_page(topic=topic.slug)
		assert page.status == 200, topic.slug
		assert page.text("h1") == topic.title
		assert page.find(".Sidebar a[aria-current=page]").text == topic.title
		for title in content.topic_headings(topic):
			assert page.find(f"h2#{markup.slug(title)}").text == f"{title}#"
		assert [link.text for link in page.find_all(".Toc a")] == content.topic_headings(topic)


def test_every_guide_page_is_in_the_navigation():

	listed = {slug for slug, _ in content.GUIDE_PAGES}

	assert listed == {path.stem for path in content.GUIDE_FOLDER.glob("*.md")}
	assert all(page.sections for page in content.GUIDE)


def test_text_and_code_are_shown(open_page):

	page = open_page(topic="styles")
	section = content.SECTIONS["Styles"].text

	assert "They are scoped to its class name" in section
	assert "They are scoped to its class name" in page.text("article")
	# Python blocks are highlighted, keywords and all
	code = page.find(".Code", text="class Card(t.div):")
	assert [node for node in code.elements() if node.attrs.get("class") == "k" and node.text == "class"]


def test_links_lead_to_the_docs_or_github(open_page):

	cli = open_page(topic="cli")
	hrefs = [link.attrs.get("href") for link in cli.find_all("article a")]

	# [Testing your app](testing.md#testing-your-app) in the Command line section
	assert "/guide/testing#testing-your-app" in hrefs
	assert "/guide/deployment#deploying" in hrefs
	assert "/guide/deployment#serving-in-production" in hrefs

	installation = open_page(topic="installation")
	hrefs = [link.attrs.get("href") for link in installation.find_all("article a")]

	assert "https://github.com/kegsmr/domino/blob/main/examples/README.md" in hrefs


def test_unknown_topics_are_not_found(open_page):

	assert open_page(topic="nothing").status == 404
