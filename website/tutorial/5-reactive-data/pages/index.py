import domino.tags as t

from components.tasks import Tasks


# pages/layout.py puts the document, the navigation and the theme around this
def page():

	return t.section() [
		t.h1() [
			"Tasks"
		],
		Tasks()
	]
