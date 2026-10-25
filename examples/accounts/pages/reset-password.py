import domino.tags as t
from domino import accounts


# Where the emailed link goes: /reset-password?token=...
def page():

	return t.section() [
		t.h1() ["Choose a new password"],
		accounts.ResetPasswordForm()
	]
