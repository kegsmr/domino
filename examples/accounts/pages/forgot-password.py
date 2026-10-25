import domino.tags as t
from domino import accounts


# Emails a link to /reset-password. In debug mode the email is printed in the terminal
def page():

	return t.section() [
		t.h1() ["Forgot your password?"],
		accounts.ForgotPasswordForm()
	]
