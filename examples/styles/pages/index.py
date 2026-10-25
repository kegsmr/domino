import domino.tags as t
from domino.components import Document

from components.cards import Board, Pill


# This file is the page at /
def page():

	page = Document(title="Styles") [
		t.h1() [
			"Styles ",
			Pill() ["new"]
		],
		Board()
	]

	# CSS variables on :root, with values for visitors who prefer a dark color scheme
	page.theme(
		surface="#ffffff", background="#f3f4f6", text="#111827", muted="#6b7280", accent="#2563eb",
		dark={"surface": "#1f2937", "background": "#111827", "text": "#f9fafb", "muted": "#9ca3af", "accent": "#60a5fa"},
	)
	page.style("body", font_family="system-ui, sans-serif", max_width="48rem", margin="2rem auto", padding="0 1rem",
		background="var(--background)", color="var(--text)")

	return page
