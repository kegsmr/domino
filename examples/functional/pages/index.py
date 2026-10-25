import domino.tags as t


NAMES = ["Ada", "Grace", "Linus"]


# pages/index.py is the page at /; pages/layout.py puts the navigation around it
def page():

	return t.section() [
		t.h1() [
			"Welcome to My Website"
		],
		t.p() [
			"This is the home page."
		],
		t.p() [
			"Say hello to:"
		],
		t.ul()([
			t.li() [
				t.a(href=f"/hello/{name}") [
					name
				]
			]
			for name in NAMES
		])
	]
