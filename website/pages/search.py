from flask import request

import domino.tags as t

import content
from components.search import highlighted


class Results(t.ul):

	css = {
		"list_style": "none", "margin": "1.5rem 0 0", "padding": 0, "max_width": "46rem",
		"a": {"display": "block", "padding": "0.8rem 0", "border_top": "1px solid var(--line)", "color": "var(--text)", "text_decoration": "none"},
		"a:hover > span": {"color": "var(--accent)"},
		"mark": {"background": "none", "color": "var(--accent)", "font_weight": "600"},
		"small": {"display": "block", "color": "var(--muted)"},
	}


# /search?q=...: every result, for Enter with nothing found and for browsers without the script
def page():

	query = request.args.get("q", "").strip()[:100]
	found = content.search(query, limit=50)

	if not query:
		summary = "Type in the search box at the top."
	elif not found:
		summary = f"Nothing found for “{query}”."
	else:
		summary = f"{len(found)} result{'s' if len(found) != 1 else ''} for “{query}”."

	return t.article() [
		t.h1() [
			"Search"
		],
		t.p(class_="lead") [
			summary
		],
		Results()([
			t.li() [
				t.a(href=entry.url) [
					highlighted(entry.title, query),
					t.small() [entry.context]
				]
			]
			for entry in found
		])
	]
