import domino.tags as t
from domino import accounts


# Where the link emailed after signing up goes (the accounts.verify_email setting is on)
def page():

	return t.section() [
		t.h1() ["Verify your email"],
		accounts.VerifyEmail()
	]
