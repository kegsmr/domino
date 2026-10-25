import domino.tags as t
from domino.components import Document

from components.clock import clock


# This file is the page at /
def page():

	return Document(title="Clock") [
		t.h1() [
			"Clock"
		],
		clock
	]
