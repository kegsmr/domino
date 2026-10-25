import domino.tags as t


# pages/contact.py is the page at /contact
def page():

	return t.section() [
		t.h1() [
			"Contact"
		],
		t.p() [
			"You can reach us at ",
			t.a(href="mailto:info@example.com") [
				"info@example.com"
			],
			"."
		]
	]
