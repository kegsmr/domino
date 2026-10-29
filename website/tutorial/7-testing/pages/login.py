import domino.tags as t
from domino import accounts


# Logs in and goes back to ?next=, or to /
def page():

	return t.section() [
		t.h1() [
			"Log in"
		],
		accounts.LoginForm()
	]
