import domino.tags as t
from domino import accounts


def page():

	return t.section() [
		t.h1() [
			"Sign up"
		],
		accounts.SignupForm()
	]
