import domino.tags as t
from domino import Document
from domino.bootstrap import BootstrapCSS, container, py_5

from components.settings import Settings


class Main(t.main, container, py_5):
	pass


# This file is the page at /
def page():

	page = Document(title="Classes and attributes") [
		Main() [
			t.h1(class_="h3 mb-4") [
				"Classes and attributes"
			],
			Settings()
		]
	]

	page.head.add_children([BootstrapCSS()])

	return page
