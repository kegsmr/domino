import domino.tags as t


# Shown with status 404, inside the layout, for URLs that no page serves
def page():

	return t.section() [
		t.h1() [
			"Page not found"
		],
		t.p() [
			t.a(href="/") [
				"Back to the home page"
			]
		]
	]
