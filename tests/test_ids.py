import domino.tags as t
from domino import Style


class Card(t.div):
	pass


def render(element):

	return element._render(indent="")


def test_plain_tags_have_no_id():

	assert render(t.div() [t.p() ["hi"]]) == "<div><p>hi</p></div>"


def test_explicit_id_is_kept():

	assert 'id="main"' in render(t.div(id="main"))


def test_components_have_an_id():

	card = Card()

	assert f'id="{card.id()}"' in render(card)


def test_bound_elements_have_an_id():

	button = t.button() ["go"]
	button.bind("click", lambda: None)
	button.after(100, lambda: None)

	assert f'id="{button.id()}"' in render(button)


def test_styled_elements_have_an_id():

	box = t.div()
	Style().style(box, color="red")

	assert 'id="' in render(box)


def test_id_requested_before_render_is_emitted():

	box = t.div()
	box_id = box.id()

	assert f'id="{box_id}"' in render(box)
