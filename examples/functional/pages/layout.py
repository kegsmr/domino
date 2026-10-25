from flask import request

import domino.tags as t
from domino.components import Document


LINKS = [
	("Home", "/"),
	("About", "/about"),
	("Contact", "/contact"),
	("Counter", "/counter"),
]


def link(text, href):

	# Marks the link to the page being shown
	current = None
	if request.path == href:
		current = "page"

	return t.a(href=href, aria_current=current) [
		text
	]


# Wraps every page in this folder and below, so each page only returns its own content. Clicking
# a link swaps the next page in without reloading, and this navigation stays as it is
def layout(content):

	# Each page's title names it, like "About · My Website"
	title = "My Website"
	for text, href in LINKS:
		if request.path == href:
			title = f"{text} · My Website"

	page = Document(title=title) [
		t.nav()([
			link(text, href)
			for text, href in LINKS
		]),
		t.main() [
			content
		],
		t.footer() [
			"Every page shares this navigation, from pages/layout.py."
		]
	]

	page.style("body", font_family="system-ui, sans-serif", max_width="40rem", margin="2rem auto", padding="0 1rem")
	page.style("nav", display="flex", gap="1rem", padding_bottom="0.75rem", border_bottom="1px solid #ddd")
	page.style("nav a[aria-current]", font_weight="bold", color="inherit", text_decoration="none")
	page.style("footer", color="#777", font_size="0.9rem", margin_top="3rem")

	return page
