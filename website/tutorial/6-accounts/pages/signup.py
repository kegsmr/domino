from domino import accounts
import domino.tags as t


def page():

	return t.section [
		t.h1 [
			"Sign up"
		],
		accounts.SignupForm()
	]
