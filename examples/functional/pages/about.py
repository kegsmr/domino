import domino.tags as t


# pages/about.py is the page at /about
def page():

	return t.section() [
		t.h1() [
			"About"
		],
		t.p() [
			"This site was built with the Domino web framework in Python."
		],
		t.p() [
			# data-domino-reload: this link loads the page from scratch, as without Domino
			t.a(href="/", data_domino_reload=True) [
				"Start over with a full page load"
			]
		]
	]
