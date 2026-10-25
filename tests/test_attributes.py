import domino.tags as t
from domino.bootstrap import col_6


class Half(t.div, col_6):
	pass


def render(element):

	return element._render(indent="")


def test_class_string_adds_classes():

	assert render(t.button(class_="btn btn-primary")) == '<button class="btn btn-primary"></button>'


def test_class_list_comes_after_component_classes():

	assert 'class="Half col-6 card shadow"' in render(Half(class_=["card", "shadow", "col-6"]))


def test_extra_classes_alone_do_not_add_an_id():

	assert "id=" not in render(t.span(class_="badge"))


def test_class_values_are_escaped():

	assert '"><script>' not in render(t.div(class_='a"><script>'))


def test_trailing_underscore_avoids_keywords():

	assert render(t.label(for_="email") ["Email"]) == '<label for="email">Email</label>'


def test_aria_and_data_attributes():

	html = render(t.button(aria_label="Close", aria_pressed="false", data_user_id=7))

	assert 'aria-label="Close"' in html
	assert 'aria-pressed="false"' in html
	assert 'data-user-id="7"' in html


def test_style_dict():

	html = render(t.p(style={"font_weight": "bold", "color": "red"}))

	assert 'style="font-weight: bold; color: red"' in html


def test_style_string_is_unchanged():

	assert 'style="color: red"' in render(t.p(style="color: red"))
