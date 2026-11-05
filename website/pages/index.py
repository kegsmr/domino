import inspect

import domino.tags as t

import components.counter
from components.code import Code
from components.counter import Counter
from components.demo import Demo
from components.shell import LOGO


FEATURES = [
	("Components in Python", "A class with State and a render() method. Events run your methods on the server, and only what changed reaches the page.", "/guide/components"),
	("Live data", "Read a Collection in render() and every open page re-renders when it changes, across processes, through MongoDB.", "/guide/reactive-data"),
	("Instant UI", "Handlers that only change their own state show at once, even on a slow connection. The server stays the source of truth.", "/guide/instant-ui"),
	("Pages from files", "pages/about.py is /about. Layouts wrap pages, and links swap pages in without reloading.", "/guide/pages"),
	("Batteries included", "Forms with validation, accounts with GitHub and Google, file uploads with progress, scoped CSS.", "/guide/forms"),
	("Tested and deployed", "Tests next to each page drive a simulated browser in a millisecond. domino serve uses every core.", "/guide/testing"),
]

INSTALL = """\
pip install domino-web
domino create myapp
cd myapp
domino run"""


class Home(t.div):

	css = {
		"max_width": "64rem",
		".section-title": {"font_size": "0.8rem", "font_weight": "600", "text_transform": "uppercase", "letter_spacing": "0.08em",
			"color": "var(--muted)", "margin": "0 0 1rem"},
		".hint": {"color": "var(--muted)", "margin": "-0.25rem 0 3.5rem"},
		"> .Code": {"max_width": "36rem"},
	}


class Hero(t.section):

	css = {
		"max_width": "46rem",
		"padding": "1.5rem 0 2.5rem",
		".mark": {"display": "inline-flex", "align_items": "center", "gap": "0.5rem", "margin_bottom": "1.25rem",
			"font": "500 0.8rem var(--mono)", "color": "var(--muted)"},
		"h1": {"font_size": "clamp(2.3rem, 6vw, 3.4rem)", "line_height": "1.05", "letter_spacing": "-0.035em", "margin": "0 0 1.1rem"},
		"h1 em": {"font_style": "normal", "color": "var(--accent)"},
		"p": {"font_size": "1.2rem", "color": "var(--text-2)", "margin": "0 0 1.75rem", "max_width": "38rem"},
		".actions": {"display": "flex", "flex_wrap": "wrap", "gap": "0.75rem"},
		".actions a": {
			"display": "inline-flex", "align_items": "center", "height": "2.75rem", "padding": "0 1.2rem",
			"border_radius": "9px", "font_weight": "600", "text_decoration": "none", "border": "1px solid var(--line)",
			"color": "var(--text)", "background": "var(--surface)", "transition": "border-color .15s, transform .15s",
		},
		".actions a:hover": {"border_color": "var(--muted)"},
		".actions a.primary": {"background": "var(--text)", "border_color": "var(--text)", "color": "var(--bg)"},
		".actions a.primary:hover": {"transform": "translateY(-1px)"},
	}


class Example(t.section):
	"""The code and, next to it, that very code running."""

	css = {
		"display": "grid", "grid_template_columns": "minmax(0, 3fr) minmax(15rem, 2fr)", "gap": "1.5rem", "align_items": "start",
		"margin": "1rem 0 3.5rem",
		".Code, .Demo": {"margin": 0},
		".Demo .stage": {"display": "grid", "place_items": "center", "min_height": "12rem"},
		".Demo button": {
			"height": "2.5rem", "font_size": "1.25rem", "border": "1px solid var(--line)", "background": "var(--surface-2)", "color": "var(--text)", "cursor": "pointer",
			"transition": "background .15s",
		},
		".Demo button:hover": {"background": "var(--hover)"},
		".note": {"margin": "0.9rem 0 0", "font_size": "0.88rem", "color": "var(--muted)"},
		"@media (max-width: 56rem)": {"grid_template_columns": "minmax(0, 1fr)"},
	}


class Features(t.section):

	css = {
		"display": "grid", "grid_template_columns": "repeat(auto-fill, minmax(15rem, 1fr))", "gap": "1rem",
		"margin": "0 0 3rem",
		"a": {
			"display": "block", "padding": "1.1rem 1.2rem", "border": "1px solid var(--line)", "border_radius": "12px",
			"color": "var(--text)", "text_decoration": "none", "background": "var(--surface)",
			"transition": "border-color .15s, box-shadow .15s",
		},
		"a:hover": {"border_color": "var(--accent-soft)", "box_shadow": "var(--shadow)"},
		"h3": {"margin": "0 0 0.35rem", "font_size": "1rem"},
		"p": {"margin": 0, "font_size": "0.9rem", "color": "var(--muted)", "line_height": "1.55"},
	}


def page():

	return Home() [
		Hero() [
			t.div(class_="mark") [
				LOGO,
				"pip install domino-web"
			],
			t.h1() [
				"Web apps in Python, ",
				t.em() ["live"],
				" in the browser."
			],
			t.p() [
				"Domino is a web framework on Flask. Write components in Python; they render on the server "
				"and stay in sync with the page, so there's no JavaScript, no API and no build step between you and your app."
			],
			t.div(class_="actions") [
				t.a(href="/tutorial", class_="primary") [
					"Start the tutorial"
				],
				t.a(href="/guide/components") [
					"Read the guide"
				],
				t.a(href="https://github.com/kegsmr/domino") [
					"GitHub"
				]
			]
		],
		t.h2(class_="section-title") [
			"A component, and it running"
		],
		Example() [
			Code(inspect.getsource(components.counter), caption="components/counter.py"),
			t.div() [
				Demo(Counter(), note="components/counter.py, on this page"),
				t.p(class_="note") [
					"Each click runs a method on the server. This one only changes its own state, "
					"so Domino shows the result before the server even answers."
				]
			]
		],
		t.h2(class_="section-title") [
			"Get started"
		],
		Code(INSTALL, "bash", caption="Terminal"),
		t.p(class_="hint") [
			"That's a working app with a page, a component, a MongoDB collection and a test. To build one "
			"step by step, follow ",
			t.a(href="/tutorial") ["the tutorial"]
		],
		t.h2(class_="section-title") [
			"What's in the box"
		],
		Features() [[
			t.a(href=href) [
				t.h3() [title],
				t.p() [text]
			]
			for title, text, href in FEATURES
		]]
	]
