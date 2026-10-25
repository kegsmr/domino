import domino.tags as t

import content


class Topics(t.div):
	"""Cards for the guide's pages, in groups."""

	css = {
		"h2": {"font_size": "0.8rem", "font_weight": "600", "text_transform": "uppercase", "letter_spacing": "0.08em",
			"color": "var(--muted)", "margin": "2.5rem 0 1rem"},
		"ul": {"display": "grid", "grid_template_columns": "repeat(auto-fill, minmax(14rem, 1fr))", "gap": "0.75rem",
			"list_style": "none", "margin": 0, "padding": 0},
		"a": {"display": "block", "height": "100%", "padding": "0.9rem 1rem", "border": "1px solid var(--line)",
			"border_radius": "10px", "color": "var(--text)", "text_decoration": "none"},
		"a:hover": {"border_color": "var(--accent-soft)", "box_shadow": "var(--shadow)"},
		"strong": {"display": "block", "margin_bottom": "0.2rem"},
		"span": {"font_size": "0.88rem", "color": "var(--muted)"},
	}


# /guide: every page of the guide and the reference
def page():

	groups = []
	for group in ("Start", "Guide", "Reference"):
		groups.append(t.h2() [group])
		groups.append(t.ul() [[
			t.li() [
				t.a(href=f"/guide/{topic.slug}") [
					t.strong() [topic.title],
					t.span() [topic.lead]
				]
			]
			for topic in content.GUIDE if topic.group == group
		]])

	return t.article() [
		t.h1() [
			"Guide"
		],
		t.p(class_="lead") [
			"Everything Domino does, a topic per page. The tutorial is the gentler way in."
		],
		Topics() [groups]
	]
