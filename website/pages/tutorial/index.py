import domino.tags as t

import content
import markup


class Steps(t.ol):
	"""The tutorial's steps, numbered."""

	css = {
		"list_style": "none", "margin": "2rem 0 0", "padding": 0, "counter_reset": "step",
		"li": {"counter_increment": "step"},
		"a": {
			"display": "grid", "grid_template_columns": "2.25rem 1fr", "gap": "0 0.9rem", "align_items": "start",
			"padding": "1rem 0", "border_top": "1px solid var(--line)", "color": "var(--text)", "text_decoration": "none",
		},
		"a::before": {
			"content": "counter(step)", "grid_row": "span 2", "display": "grid", "place_items": "center",
			"width": "2.25rem", "height": "2.25rem", "border_radius": "50%", "border": "1px solid var(--line)",
			"font": "600 0.9rem var(--mono)", "color": "var(--muted)", "transition": "all .15s",
		},
		"a:hover::before": {"border_color": "var(--accent)", "color": "var(--accent)"},
		"strong": {"font_weight": "600"},
		"span": {"color": "var(--muted)", "font_size": "0.92rem"},
	}


# /tutorial: what the tutorial builds, and its steps
def page():

	return t.article() [
		t.p(class_="eyebrow") [
			"Tutorial"
		],
		t.h1() [
			"Build a shared task list"
		],
		t.p(class_="lead") [
			"Eight short steps take you from a single page to a task list that updates live in every open "
			"window, with accounts, tests and a production server. Each step is a complete app, and its "
			"live demo is that app's own component, running on the page. The apps are in ",
			t.a(href=markup.repository_link("docs/tutorial/")) ["docs/tutorial/"]
		],
		Steps() [[
			t.li() [
				t.a(href=f"/tutorial/{step.slug}") [
					t.strong() [step.title],
					t.span() [step.lead]
				]
			]
			for step in content.STEPS
		]]
	]

