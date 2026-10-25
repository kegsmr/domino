import domino.tags as t
from domino.components import Document

from components.settings import Settings


# This file is the page at /
def page():

	page = Document(title="Loading and errors") [
		t.h1() [
			"Loading and errors"
		],
		Settings()
	]

	page.style("body", font_family="system-ui, sans-serif", max_width="32rem", margin="2rem auto")
	page.style("button", font="inherit", padding="0.5rem 1rem")

	# Domino marks the button that fired with data-loading (and aria-busy) until the
	# response arrives; the rest is up to your CSS
	page.style("button[data-loading]", opacity="0.6", cursor="progress")
	page.style(".save[data-loading]", font_size="0")
	page.style(".save[data-loading]::after", content="'Saving\\2026'", font_size="1rem")

	return page
