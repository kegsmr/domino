import domino.tags as t
from domino import Style
from domino.bootstrap import col_6, container_fluid, d_flex, row


class Grid(t.div, container_fluid):
	pass


class Half(t.div, col_6, d_flex):
	pass


class Panel(Half):
	pass


def classes(element):

	return element._render(indent="").split('class="')[1].split('"')[0].split()


def test_mixin_underscores_become_hyphens():

	assert classes(Grid()) == ["Grid", "container-fluid"]


def test_inherited_classes_are_kept_once():

	assert classes(Panel()) == ["Panel", "Half", "col-6", "d-flex"]


def test_plain_tags_have_no_class():

	assert 'class="' not in t.div()._render(indent="")


def test_style_selector_matches_rendered_class():

	stylesheet = Style()
	stylesheet.style(col_6, color="red")
	stylesheet.style(row, gap="1rem")

	css = stylesheet.compute().inner()

	assert ".col-6 {" in css
	assert ".row {" in css
