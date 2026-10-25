import domino.tags as t
from domino import accounts


# Only for users who have clicked the link in their sign-up email
@accounts.login_required(verified=True)
def page():

	return t.section() [
		t.h1() ["Members"],
		t.p() [f"Your email, {accounts.current_user()['email']}, is verified."]
	]
