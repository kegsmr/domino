import domino.tags as t
from domino import Document

from components.gallery import Gallery


# This file is the page at /
def page():

	page = Document(title="Uploads") [
		t.h1() [
			"Uploads"
		],
		Gallery()
	]

	page.style("body", font_family="system-ui, sans-serif", max_width="40rem", margin="2rem auto")

	return page
