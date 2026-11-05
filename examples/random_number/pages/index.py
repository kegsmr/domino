import domino.tags as t
from domino import Document

from components.random_number import RandomNumber


# This file is the page at /
def page():

	return Document(title="Random Number") [
		t.h1() [
			"Random Number"
		],
		RandomNumber()
	]
