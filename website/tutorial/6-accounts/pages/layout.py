from flask import request

import domino.tags as t
from domino import accounts
from domino.components import Document


LINKS = [
	("Tasks", "/"),
	("About", "/about"),
]


def layout(content):

	page = Document(title="Tasks") [
		t.nav()([
			t.a(href=href, aria_current="page" if request.path == href else None) [
				text
			]
			for text, href in LINKS
		] + [
			# "Signed in as …" and Log out, or Log in and Sign up; updates when you log in or out
			accounts.UserMenu()
		]),
		t.main() [
			content
		]
	]

	page.theme(
		background="#f6f6f8", surface="#ffffff", text="#18181b", muted="#71717a", line="#e4e4e7", accent="#4f5bd5",
		dark={"background": "#111113", "surface": "#1c1c1f", "text": "#ededef", "muted": "#a1a1aa", "line": "#2e2e33", "accent": "#7c86f0"},
	)
	page.style("body", font_family="system-ui, sans-serif", background="var(--background)", color="var(--text)",
		max_width="32rem", margin="3rem auto", padding="0 1rem")
	page.style("nav", {"display": "flex", "gap": "1rem", "a": {"color": "var(--muted)"}, "a[aria-current]": {"color": "var(--text)", "font_weight": "600"}})
	page.style(".UserMenu", margin_left="auto")
	page.style("main form", {"display": "grid", "gap": "0.75rem", "label": {"display": "grid", "gap": "0.25rem"}})

	return page
