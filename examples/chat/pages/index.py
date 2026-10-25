import domino.tags as t
from domino import Document

from components.chat import Chat


# This file is the page at /
def page():

	page = Document(title="Chat") [
		t.h1() [
			"Chat"
		],
		t.p() [
			"Open this page in two windows: messages appear in both instantly."
		],
		Chat()
	]

	page.style("body", font_family="system-ui, sans-serif", max_width="32rem", margin="2rem auto")

	return page
