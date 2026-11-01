from urllib.parse import quote

from markupsafe import Markup, escape

import domino.tags as t
from domino import State, redirect

import content


MAGNIFIER = Markup(
	'<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.2" '
	'stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>'
)


class Search(t.div):
	"""Search as you type, on the server: each pause in typing sends the query, and only the
	results list comes back. Enter goes to the first result."""

	query = State("")

	css = {
		"position": "relative",
		"width": "min(22rem, 100%)",
		"input": {
			"width": "100%", "box_sizing": "border-box", "height": "2.25rem", "padding": "0 2.5rem 0 2.1rem",
			"font": "inherit", "font_size": "0.9rem", "color": "var(--text)",
			"background": "var(--surface-2)", "border": "1px solid var(--line)", "border_radius": "8px",
			"outline": "none", "transition": "border-color .15s, box-shadow .15s",
		},
		"input:focus": {"border_color": "var(--accent)", "box_shadow": "0 0 0 3px var(--accent-bg)", "background": "var(--surface)"},
		"input::-webkit-search-cancel-button": {"display": "none"},
		"form": {"position": "relative", "margin": 0},
		".icon": {"position": "absolute", "left": "0.7rem", "top": "0.55rem", "color": "var(--muted)", "pointer_events": "none", "line_height": 0},
		".key": {
			"position": "absolute", "right": "0.55rem", "top": "0.5rem", "font": "500 0.72rem/1 var(--mono)",
			"color": "var(--muted)", "border": "1px solid var(--line)", "border_radius": "4px", "padding": "0.2rem 0.35rem",
		},
		":focus-within .key": {"display": "none"},
		".results": {
			"display": "none", "position": "absolute", "top": "calc(100% + 0.4rem)", "left": 0, "right": 0, "z_index": "30",
			"margin": 0, "padding": "0.35rem", "list_style": "none",
			"background": "var(--surface)", "border": "1px solid var(--line)", "border_radius": "10px", "box_shadow": "var(--shadow-lg)",
			"max_height": "min(24rem, 70vh)", "overflow_y": "auto",
		},
		# Shown while the search has focus (a result link keeps it, so clicking one works)
		":focus-within .results": {"display": "block"},
		".results a": {"display": "block", "padding": "0.45rem 0.65rem", "border_radius": "6px", "color": "var(--text)", "text_decoration": "none"},
		".results a:hover, .results a:focus": {"background": "var(--accent-bg)", "outline": "none"},
		".results small": {"display": "block", "color": "var(--muted)", "font_size": "0.75rem"},
		".results mark": {"background": "none", "color": "var(--accent)", "font_weight": "600"},
		".empty": {"padding": "0.6rem 0.65rem", "color": "var(--muted)", "font_size": "0.9rem"},
		"@media (max-width: 40rem)": {".key": {"display": "none"}, ".results": {"position": "fixed", "left": "0.5rem", "right": "0.5rem", "top": "3.5rem"}},
	}


	def render(self):

		query = self.query.strip()
		found = content.search(query) if query else []

		results = []
		if query:
			results = [t.ul(class_="results", aria_label="Search results") [[
				t.li() [
					t.a(href=entry.url, tabindex="0") [
						highlighted(entry.title, query),
						t.small() [
							entry.context
						]
					]
				]
				for entry in found
			] or [
				t.li(class_="empty") [
					f"Nothing found for “{query}”"
				]
			]]]

		# Without the script (or before it loads) the form still works, as a plain GET. Its events
		# are bound while rendering, so each render of the results binds them again
		return [
			t.form(role="search", action="/search", on_submit=self.go) [[
				t.span(class_="icon", aria_hidden="true") [
					MAGNIFIER
				],
				t.input(type="search", name="q", value=self.query, placeholder="Search", aria_label="Search the docs",
					autocomplete="off", spellcheck="false", on_input=self.search, debounce=120),
				t.span(class_="key", aria_hidden="true") [
					"/"
				],
			] + results]
		]


	def search(self, event):

		self.query = str(event.value or "")[:100]


	def go(self, event):

		query = str(event.form.get("q") or "").strip()[:100]
		found = content.search(query)
		redirect(found[0].url if found else f"/search?q={quote(query)}")


def highlighted(title, query):
	"""The title, with the words of the query marked."""

	words = sorted({word for word in query.lower().split()}, key=len, reverse=True)
	lower = title.lower()

	marked = [False] * len(title)
	for word in words:
		start = lower.find(word)
		while start != -1:
			for index in range(start, start + len(word)):
				marked[index] = True
			start = lower.find(word, start + len(word))

	# One string, since separate elements would be written on lines of their own, and the
	# line breaks between them would show as spaces
	parts = []
	index = 0
	while index < len(title):
		end = index
		while end < len(title) and marked[end] == marked[index]:
			end += 1
		text = escape(title[index:end])
		parts.append(Markup(f"<mark>{text}</mark>") if marked[index] else text)
		index = end

	return t.span() [
		Markup("").join(parts)
	]
