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
	page.style("label", display="block", margin="0.75rem 0")
	page.style("fieldset", border="1px solid #ddd", border_radius="8px", padding="1rem 1.5rem")
	page.style("dt", font_weight="600")

	return page
