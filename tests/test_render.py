import domino.tags as t
from markupsafe import Markup


def render(element):

	return element._render(indent="")


def test_text_is_escaped():

	html = render(t.p() ["<script>alert(1)</script> & co"])

	assert "<script>" not in html
	assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; co" in html


def test_inner_is_escaped():

	html = render(t.p(None, "<b>hi</b>"))

	assert "&lt;b&gt;hi&lt;/b&gt;" in html


def test_markup_is_not_escaped():

	html = render(t.p() [Markup("<b>hi</b>")])

	assert "<b>hi</b>" in html


def test_attributes_are_escaped():

	html = render(t.a(href='x" onclick="alert(1)') ["hi"])

	assert 'onclick="alert(1)"' not in html
	assert 'href="x&#34; onclick=&#34;alert(1)"' in html


def test_script_and_style_are_raw():

	assert "a > b" in render(t.style(None, "a > b { color: red; }"))
	assert "1 < 2 && 3 > 2" in render(t.script() ["1 < 2 && 3 > 2"])


def test_boolean_and_falsy_attributes():

	html = render(t.input(value=0, disabled=True, checked=False, alt="", title=None))

	assert 'value="0"' in html
	assert " disabled" in html and 'disabled="' not in html
	assert "checked" not in html
	assert 'alt=""' in html
	assert "title" not in html


def test_nested_elements_are_not_double_escaped():

	html = render(t.div() [t.p() ["a & b"]])

	assert "<p" in html
	assert "a &amp; b" in html


def test_whitespace_inside_pre_and_textarea_is_kept_as_written():

	# Indented as usual around them, but what they hold is their content (a textarea's value)
	html = t.div() [t.pre() ["a\n  b", t.span() ["c"]], t.textarea(name="note") ["x"], t.pre(inner="l1\nl2"), t.p() ["y"]]._render()

	assert "    <pre>a\n  b<span>c</span></pre>\n" in html
	assert "    <textarea name=\"note\">x</textarea>\n" in html
	assert "<pre>l1\nl2</pre>" in html
	assert "    <p>\n        y\n    </p>\n" in html
