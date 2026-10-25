import domino.tags as t
from domino.components import Document

from components.signup_form import SignupForm


# This file is the page at /
def page():

	page = Document(title="Forms") [
		t.h1() [
			"Forms"
		],
		SignupForm()
	]

	page.style("body", font_family="system-ui, sans-serif", max_width="32rem", margin="2rem auto")

	return page
