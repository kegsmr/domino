from domino import accounts
import domino.tags as t


# Logs in and goes back to ?next=, or to /
def page():

	return t.section [
		t.h1 [
			"Log in"
		],
		accounts.LoginForm()
	]
