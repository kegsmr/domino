import domino.tags as t
from domino.components import Document

from components.tasks import Tasks


# pages/index.py is the page at /
def page():

	page = Document(title="Tasks") [
		t.main() [
			t.h1() [
				"Tasks"
			],
			Tasks()
		]
	]

	# CSS variables on :root (--surface, ...), with other values when the system prefers dark
	page.theme(
		background="#f6f6f8", surface="#ffffff", text="#18181b", muted="#71717a", line="#e4e4e7", accent="#4f5bd5",
		dark={"background": "#111113", "surface": "#1c1c1f", "text": "#ededef", "muted": "#a1a1aa", "line": "#2e2e33", "accent": "#7c86f0"},
	)
	page.style("body", font_family="system-ui, sans-serif", background="var(--background)", color="var(--text)",
		max_width="32rem", margin="3rem auto", padding="0 1rem")

	return page
