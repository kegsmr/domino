import domino.tags as t
from domino import accounts

from components.notes import Notes


# Visitors who aren't signed in are sent to /login, and come back here after
@accounts.login_required
def page():

	return t.section() [
		t.h1() ["Private"],
		Notes()
	]
