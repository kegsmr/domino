import domino.tags as t
from domino.components import Document
from domino.bootstrap import (
	BootstrapCSS, container, row, col_4, d_flex, justify_content_between,
	align_items_center, bg_dark, bg_light, bg_white, text_white, text_muted, text_center,
	font_weight_bold, p_3, p_4, py_5, mb_0, mb_3, mb_4,
)


# Each component mixes Bootstrap utility classes into a tag; class names like
# col_4 render as Bootstrap's col-4

class Navbar(t.nav, bg_dark, text_white, d_flex, justify_content_between, align_items_center, p_3):
	pass


class Hero(t.header, bg_light, text_center, py_5, mb_4):
	pass


class Grid(t.div, container):
	pass


class Row(t.div, row):
	pass


class Third(t.div, col_4, mb_4):
	pass


class Card(t.div, bg_white, p_4):
	pass


class CardTitle(t.h4, font_weight_bold, mb_3):
	pass


class Muted(t.p, text_muted, mb_0):
	pass


class Footer(t.footer, text_center, text_muted, py_5):
	pass


FEATURES = [
	("Components", "Write HTML as Python classes and compose them like any other object."),
	("Events", "Bind clicks and form submits to Python methods; the page updates without reloading."),
	("Bootstrap", "Mix utility classes such as col_4 or bg_dark into any tag to style it."),
]


# This file is the page at /
def page():

	page = Document(title="Domino + Bootstrap") [
		Navbar() [
			t.span() [
				"Domino"
			],
			t.span() [
				"Bootstrap grid demo"
			]
		],
		Hero() [
			t.h1() [
				"Domino + Bootstrap"
			],
			Muted() [
				"Layout and spacing below come only from Bootstrap utility classes."
			]
		],
		Grid() [
			Row()([
				Third() [
					Card() [
						CardTitle() [
							title
						],
						Muted() [
							description
						]
					]
				]
				for title, description in FEATURES
			])
		],
		Footer() [
			"Built with Domino"
		]
	]

	page.head.add_children([BootstrapCSS()])

	return page

