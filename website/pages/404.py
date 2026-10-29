import domino.tags as t


# Shown with status 404, inside the layout, for URLs no page serves
def page():

	return t.article() [
		t.p(class_="eyebrow") [
			"404"
		],
		t.h1() [
			"There's no page here"
		],
		t.p(class_="lead") [
			"Try the search at the top (press / to jump to it), or start from the ",
			t.a(href="/") ["overview"]
		]
	]
