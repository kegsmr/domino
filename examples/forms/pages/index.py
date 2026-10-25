import domino.tags as t
from domino.components import Document

from components.seat_picker import SeatPicker
from components.signup import Onboarding


# This file is the page at /
def page():

	page = Document(title="Forms") [
		t.h1() [
			"Forms"
		],
		Onboarding(),
		t.h2() [
			"Raw controls"
		],
		SeatPicker()
	]

	page.style("body", font_family="system-ui, sans-serif", max_width="32rem", margin="2rem auto", padding="0 1rem")

	return page
