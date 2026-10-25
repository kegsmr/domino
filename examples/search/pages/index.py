import domino.tags as t
from domino import Document

from components.search import Search


# This file is the page at /
def page():

	page = Document(title="Live search") [
		t.h1() [
			"Live search"
		],
		Search()
	]

	page.style("body", font_family="system-ui, sans-serif", max_width="28rem", margin="2rem auto")

	return page
