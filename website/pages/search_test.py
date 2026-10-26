# Tests for the search box every page has (components/search.py) and pages/search.py

import content


def title(link):
	"""A result's title, without the page or section under it."""

	return next(element for element in link.elements() if element.tag == "span").text


def test_typing_shows_matching_pages_and_headings(open_page):

	page = open_page("/")

	assert page.find_all(".Search .results") == []

	page.type(".Search input", "mongo")
	results = [(title(link), link.attrs["href"]) for link in page.find_all(".Search .results a")]

	assert ("Reactive data & MongoDB", "/guide/reactive-data") in results
	assert ("MongoDB in tests", "/guide/testing#mongodb-in-tests") in results
	# Pages before headings on them
	assert results.index(("Reactive data & MongoDB", "/guide/reactive-data")) < results.index(("MongoDB in tests", "/guide/testing#mongodb-in-tests"))
	assert page.find(".Search .results mark").text.lower() == "mongo"


def test_finds_tutorial_steps_and_their_headings(open_page):

	page = open_page("/")
	page.type(".Search input", "layout")

	hrefs = [link.attrs["href"] for link in page.find_all(".Search .results a")]

	assert hrefs[0] == "/tutorial/4-pages-and-layouts"
	assert "/tutorial/4-pages-and-layouts#a-layout" in hrefs


def test_every_word_must_match(open_page):

	page = open_page("/")
	page.type(".Search input", "file uploads")

	assert page.find(".Search .results a").attrs["href"] == "/guide/uploads"

	page.type(".Search input", "zebra")

	assert page.text(".Search .results") == "Nothing found for “zebra”"


def test_enter_goes_to_the_first_result(open_page):

	page = open_page("/")
	# Typing re-renders the results; the form must still submit after that
	page.type(".Search input", "deploy")
	page.submit(".Search form")

	assert page.path == "/tutorial/8-deploying"


def test_the_search_page_lists_every_result(page):

	page.load("/search?q=state")

	assert page.text("h1") == "Search"
	assert [link.attrs["href"] for link in page.find_all(".Results a")] == [entry.url for entry in content.search("state", limit=50)]
	assert page.find(".Results a").attrs["href"] == "/guide/state"


def test_enter_with_nothing_found_shows_the_search_page(open_page):

	page = open_page("/")
	page.fill(".Search input", "zebra")
	page.submit(".Search form")

	assert page.path == "/search"
	assert page.text(".lead") == "Nothing found for “zebra”."
