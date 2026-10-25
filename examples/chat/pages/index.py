import domino.tags as t
from domino.components import Document

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
	page.style(".messages", list_style="none", min_height="12rem", border="1px solid #ddd", border_radius="8px", padding="0.5rem 1rem")
	page.style("form", display="flex", gap="0.5rem")
	page.style("input", font="inherit", padding="0.4rem", min_width="0")
	page.style("input[name=name]", width="7rem")
	page.style("input[name=text]", flex="1")

	return page
