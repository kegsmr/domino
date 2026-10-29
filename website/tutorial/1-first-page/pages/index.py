import domino.tags as t

from components.tasks import Tasks


# pages/index.py is the page at /
def page():

	return t.main() [
		t.h1() [
			"Tasks"
		],
		Tasks()
	]
