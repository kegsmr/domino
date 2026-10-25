# Tests for pages/guide/[topic].py: the guide is README.md's sections, all of them

import content
import markup


def test_every_topic_renders_its_readme_sections(open_page):

	for topic in content.GUIDE:
		page = open_page(topic=topic.slug)
		assert page.status == 200, topic.slug
		assert page.text("h1") == topic.title
		assert page.find(".Sidebar a[aria-current=page]").text == topic.title
		for title in content.topic_headings(topic):
			assert page.find(f"h2#{markup.slug(title)}").text == f"{title}#"
		assert [link.text for link in page.find_all(".Toc a")] == content.topic_headings(topic)


def test_every_readme_section_is_in_the_guide():

	shown = [title for topic in content.GUIDE for title in topic.sections]

	assert sorted(shown) == sorted(content.SECTIONS)
	assert len(shown) == len(set(shown))


def test_readme_text_and_code_are_shown(open_page):

	page = open_page(topic="styles")
	section = content.SECTIONS["Styles"].text

	assert "They are scoped to its class name" in section
	assert "They are scoped to its class name" in page.text("article")
	# Python blocks are highlighted, keywords and all
	code = page.find(".Code", text="class Card(t.div):")
	assert [node for node in code.elements() if node.attrs.get("class") == "k" and node.text == "class"]


def test_readme_links_lead_to_the_docs_or_github(open_page):

	cli = open_page(topic="cli")
	hrefs = [link.attrs.get("href") for link in cli.find_all("article a")]

	# [Testing your app](#testing-your-app) in the Command line section
	assert "/guide/testing#testing-your-app" in hrefs
	assert "/guide/deployment#deployment" in hrefs

	installation = open_page(topic="installation")
	hrefs = [link.attrs.get("href") for link in installation.find_all("article a")]

	assert "https://github.com/kegsmr/domino/blob/main/examples/README.md" in hrefs


def test_unknown_topics_are_not_found(open_page):

	assert open_page(topic="nothing").status == 404
