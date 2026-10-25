import domino.tags as t


# pages/hello/[name].py is the page at /hello/<name>; that part of the URL arrives as `name`
def page(name):

	return t.section() [
		t.h1() [
			f"Hello, {name}!"
		],
		t.p() [
			"This page's URL has a parameter: change the name in the address bar."
		]
	]
