import domino.tags as t
from domino.components import Document

# The app's folder is importable, so pages can use its components
from components.counter import CounterComponent


# This file is the page at /
def page():

	return Document(title="Counter") [
		t.h1() [
			"Counter"
		],
		CounterComponent()
	]
