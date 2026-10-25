"""Template string (t"...") tests. Python 3.14 syntax, so test_templates.py imports this only there."""

import json

import pytest

import domino.tags as t
from domino import Domino, Element, Markup, State, TemplateError, html, templates, wait
from domino.components import Document


def render(element):

	return element._render(indent="")


def load(app):

	client = app.test_client()
	page = client.get("/").get_data(as_text=True)
	page_id = page.split('data-domino-page="')[1].split('"')[0]

	return client, page_id, page


class Counter(t.div):

	count = State(0)


	def render(self):

		return html(t"""
			<p>Count: {self.count}</p>
			<button on_click={self.increment}>+</button>
		""")


	def increment(self):

		self.count += 1


class Card(t.section):
	pass


def test_text_is_escaped():

	text = "<script>alert(1)</script> & co"

	assert render(html(t"<p>{text}</p>")) == "<p>&lt;script&gt;alert(1)&lt;/script&gt; &amp; co</p>"


def test_markup_is_raw():

	assert render(html(t"<p>{Markup('<b>hi</b>')} &amp; {'<i>'}</p>")) == "<p><b>hi</b> &amp; &lt;i&gt;</p>"


def test_entities_in_text_and_attributes():

	assert render(html(t'<p title="a &amp; b">1 &lt; 2&nbsp;</p>')) == '<p title="a &amp; b">1 &lt; 2\xa0</p>'


def test_nested_lists_and_falsy_values():

	items = ["a", "b"]
	element = html(t"<ul>{[html(t'<li>{item}</li>') for item in items]}{None}{False}{[[html(t'<li>c</li>')]]}</ul>")

	assert render(element) == "<ul><li>a</li><li>b</li><li>c</li></ul>"


def test_elements_and_classes_as_children():

	assert render(html(t"<div>{t.span() ['x']}</div>")) == "<div><span>x</span></div>"


def test_conversions_and_format_specs():

	value = 3.14159

	assert render(html(t"<p>{value:.2f} {'x'!r}</p>")) == "<p>3.14 &#39;x&#39;</p>"


def test_attributes_quoted_unquoted_and_boolean():

	name = "email"
	element = html(t"<input type=text name='{name}' id=\"f-{name}\" required value={0} disabled={False}>")

	assert render(element) == '<input type="text" name="email" id="f-email" required value="0">'


def test_class_list_style_dict_for_and_aria():

	classes = ["btn", "primary"]
	style = {"font_weight": "bold"}
	element = html(t'<label class={classes} style={style} for="x" aria-label="Close">x</label>')

	assert render(element) == '<label class="btn primary" style="font-weight: bold" for="x" aria-label="Close">x</label>'


def test_spread_attributes():

	attributes = {"data-user-id": 7, "title": "hi"}

	assert render(html(t"<div {attributes}></div>")) == '<div data-user-id="7" title="hi"></div>'


def test_tags_are_domino_tag_classes():

	element = html(t"<DIV><my-widget size=2 /></DIV>")

	assert type(element) is t.div
	assert type(element.__children__[0]) is Element
	assert render(element) == '<div><my-widget size="2"></my-widget></div>'


def test_void_and_self_closing_tags():

	assert render(html(t"<p>a<br>b<br/>c<img src=x.png /></p>")) == '<p>a<br>b<br>c<img src="x.png"></p>'


def test_script_and_style_are_raw_text():

	data = {"a": "</script>"}
	color = "red"
	element = html(t"<div><script>if (1 < 2 && {data}) {{}}</script><style>p > a {{ color: {color} }}</style></div>")

	assert render(element) == (
		'<div><script>if (1 < 2 && {"a": "\\u003c/script\\u003e"}) {}</script>'
		"<style>p > a { color: red }</style></div>"
	)


def test_comments_and_doctype_are_dropped():

	assert render(html(t"<!DOCTYPE html><div><!-- <p>no</p> -->yes</div>")) == "<div>yes</div>"


def test_whitespace_is_collapsed_and_trimmed():

	element = html(t"""
		<p>
			Hello,
			<b>world</b> <i>again</i>
		</p>
	""")

	assert render(element) == "<p>Hello, <b>world</b> <i>again</i></p>"


def test_pre_keeps_whitespace():

	assert render(html(t"<pre>a\n  b</pre>")) == "<pre>a\n  b</pre>"


def test_single_root_is_an_element_and_several_are_a_list():

	assert isinstance(html(t"  <p>a</p>\n"), t.p)

	several = html(t"<p>a</p>\n<p>b</p>")
	assert isinstance(several, list) and len(several) == 2

	assert html(t"just {'text'}") == ["just text"]


def test_component_tags_with_attributes_and_children():

	element = html(t'<div><{Card} title="x" class="wide"><p>inside</p></{Card}><{Card} /></div>')
	card = element.__children__[0]

	assert isinstance(card, Card)
	assert card.__attributes__["title"] == "x"
	assert '<section class="Card wide" title="x"' in render(element)
	assert "<p>inside</p></section>" in render(element)


def test_component_tag_closed_by_another_component_fails():

	with pytest.raises(TemplateError, match="closes a different component"):
		html(t"<{Card}></{Counter}>")


def test_f_strings_are_rejected():

	with pytest.raises(TypeError, match="template string"):
		html(f"<p>{1}</p>")


@pytest.mark.parametrize("source, message", [
	("<div>\n<p>\n</div>", "line 3: </div> doesn't match <p> from line 2"),
	("<div>\n  <span>", "line 2: <span> is never closed"),
	("<p></p>\n</p>", "line 2: </p> closes nothing"),
	("<!-- open", "line 1: comment is never closed"),
])
def test_errors_name_the_line_and_tag(source, message):

	with pytest.raises(TemplateError) as error:
		html(eval(f"t{source!r}"))

	assert str(error.value) == message


def test_interpolation_inside_a_tag_name_fails():

	level = 2

	with pytest.raises(TemplateError, match="part of a tag name"):
		html(t"<h{level}>x</h{level}>")


def test_each_template_is_parsed_once(monkeypatch):

	calls = []
	parse = templates._parse

	def counting(strings):

		calls.append(strings)
		return parse(strings)

	monkeypatch.setattr(templates, "_parse", counting)
	monkeypatch.setattr(templates, "_cache", {})

	for number in range(5):
		assert render(html(t"<p>{number}</p>")) == f"<p>{number}</p>"

	assert len(calls) == 1


def test_on_click_binds_and_round_trips():

	app = Domino(__name__)

	@app.route("/")
	def index():

		return Document() [Counter()]

	client, page_id, page = load(app)
	event_id = page.split('data-event-id="')[1].split('"')[0]
	assert "Count: 0" in page

	data = client.post("/_domino/events", json={"page_id": page_id, "event_id": event_id}).get_json()
	wait()

	assert "Count: 1" in data["html"]
	# The re-rendered button keeps its event id, so the next click still works
	assert f'data-event-id="{event_id}"' in data["html"]


def test_debounce_applies_to_template_events():

	element = html(t"<input on_input={print} debounce=250>")

	assert 'data-debounce-input="250"' in render(element)


def test_optimistic_predictions_for_a_template_counter():

	app = Domino(__name__)

	@app.route("/")
	def index():

		return Document() [Counter()]

	_, _, page = load(app)
	script = page.split("data-domino-predict>")[1].split("</script>")[0]
	graph = json.loads(script)

	# A counter can go up forever, so just the next step
	assert len(graph["edges"]) == 1 and len(graph["states"]) == 2
	assert "Count: 1" in graph["states"][1]
