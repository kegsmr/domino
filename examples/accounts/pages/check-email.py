import domino.tags as t
from domino import accounts


# Where @accounts.login_required(verified=True) sends users who haven't verified their email
def page():

	return t.section() [
		t.h1() ["Check your email"],
		accounts.CheckEmail()
	]
