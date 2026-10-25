import domino.tags as t


def page():

	return t.section() [
		t.h1() ["Accounts"],
		t.p() [
			t.a(href="/signup?next=/private") ["Sign up"],
			", then add notes on the private page. They're only shown to you."
		]
	]
