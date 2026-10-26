import domino.tags as t


# pages/about.py is the page at /about. Links between pages swap them in without reloading
def page():

	return t.section() [
		t.h1() [
			"About"
		],
		t.p() [
			"A task list written in Python, with ",
			t.a(href="https://github.com/kegsmr/domino") [
				"Domino"
			]
		]
	]
