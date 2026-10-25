import domino.tags as t


# pages/about.py is the page at /about
def page():

	return t.section() [
		t.h1() [
			"About"
		],
		t.p() [
			"This site was built with the Domino web framework in Python."
		]
	]
