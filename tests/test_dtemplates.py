"""Domino templates (domino.dtemplates): HTML for markup, components as capitalized tags, lists and
conditions as attributes, values and handlers from Python."""

import importlib.util
import json
import logging
import os
import sys
import textwrap
import time
import uuid

import pytest
from markupsafe import Markup

import domino.tags as t
from domino import Domino, State, TemplateError, template
from domino import dtemplates
from domino.components import Document


def write(path, text):

	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")

	return path


def import_file(path):

	# A name of its own, so modules of different tests never clash
	name = f"domino_dt_{uuid.uuid4().hex[:8]}"
	spec = importlib.util.spec_from_file_location(name, path)
	module = importlib.util.module_from_spec(spec)
	sys.modules[name] = module
	spec.loader.exec_module(module)

	return module


def component(tmp_path, python, html, name="widget"):
	"""components/<name>.py and components/<name>.html; returns the module."""

	write(tmp_path / "components" / f"{name}.html", html)

	return import_file(write(tmp_path / "components" / f"{name}.py", "import domino.tags as t\nfrom domino import State\n\n\n" + textwrap.dedent(python).lstrip("\n")))


def serve(tmp_path, make, **options):

	app = Domino("app", root_path=str(tmp_path), **options)
	app.testing = True

	@app.route("/")
	def index():

		return Document() [make()]

	return app


def make_app(tmp_path):

	app = Domino("app", root_path=str(tmp_path))
	app.testing = True

	return app


def html_of(app, path="/"):
	"""The page's HTML as the server sent it (TestPage.html is parsed and written again)."""

	return app.test_client().get(path).get_data(as_text=True)


def inner(html, selector):
	"""What's inside the element: its HTML, without predictions."""

	start = html.index(">", html.index(f'class="{selector}')) + 1
	html = html[start:]
	if "\n    </body>" in html:
		html = html[:html.index("\n    </body>")]

	return html.split("<script type=\"application/json\" data-domino-predict>")[0].rsplit("</", 1)[0]


# Parsing

def test_markup_is_kept_as_written(tmp_path):

	module = component(tmp_path, "class Widget(t.div):\n\tpass\n", """
		<Widget>
			<!-- a comment, left out -->
			<p class=lead data-x='1' hidden>Tom &amp; Jerry &lt;3</p>
			<img src="a.png" alt=""><br/><input disabled>
			<pre>
			  two  spaces
			</pre>
			<svg viewBox="0 0 1 1"><linearGradient id="g"></linearGradient></svg>
			<div />
		</Widget>
	""")
	html = inner(html_of(serve(tmp_path, module.Widget)), "Widget")

	assert "comment" not in html
	assert "<p class=lead data-x='1' hidden>Tom &amp; Jerry &lt;3</p>" in html
	assert '<img src="a.png" alt=""><br><input disabled>' in html
	assert "<pre>\n\t  two  spaces\n\t</pre>" in html
	assert '<svg viewBox="0 0 1 1"><linearGradient id="g"></linearGradient></svg>' in html
	assert "<div></div>" in html


def test_no_spaces_are_added_around_inline_elements(tmp_path):

	module = component(tmp_path, "class Note(t.p):\n\tname = 'Domino'\n", "<Note>Made with <a href=\"/\">{{ name }}</a>.</Note>")

	html = html_of(serve(tmp_path, module.Note))

	assert '>Made with <a href="/">Domino</a>.</p>' in html


def test_a_page_template_keeps_its_doctype_and_entities(tmp_path):

	write(tmp_path / "home.html", """
		<!DOCTYPE html>
		<html lang="en"><head><title>{{ title }}</title></head><body><p>&copy; {{ year }}</p></body></html>
	""")
	app = make_app(tmp_path)

	@app.route("/")
	def index():

		return template("home.html", title="A & B", year=2026)

	html = app.test_client().get("/").get_data(as_text=True)

	assert html.startswith("<!DOCTYPE html>\n<html ") and "lang=\"en\"" in html and "data-domino-page=" in html
	assert "<title>A &amp; B</title>" in html and "<p>&copy; 2026</p>" in html
	assert '<script class="Core" src="/_domino/core"' in html.split("</head>")[0]


@pytest.mark.parametrize("source, message", [
	("<W><p>never closed</W>", "</W> doesn't close <p> from line 1, column 4"),
	("<W>\n  <ul>\n</W>", "</W> doesn't close <ul> from line 2, column 3"),
	("<W><li>", "<li> is never closed"),
	("<W></br></W>", "<br> is a void element"),
	("<W><p class=\"{{ kind }}\">x</p></W>", ":class=\"helper\""),
	("<W>{{ a + b }}</W>", "unexpected '+'"),
	("<W>{{ x</W>", "{{ is never closed"),
	("<W><p else>x</p></W>", "needs an element with if="),
	("<W><p each=\"items\">x</p></W>", "each=\"item in items\""),
	("<W><p on-click>x</p></W>", "an event needs a handler"),
])
def test_syntax_errors_say_where(tmp_path, source, message):

	path = write(tmp_path / "w.html", source)

	with pytest.raises(TemplateError) as error:
		dtemplates.parse_file(str(path))

	assert message in str(error.value)
	assert "w.html:" in str(error.value)


# Values

WIDGET = """
class Widget(t.div):

	count = State(3)
	label = "<b>bold</b>"
	user = {"name": "Ada", "tags": ["x", "y"]}

	def init(self):
		self.safe = Markup("<i>ok</i>")
		self.nothing = None

	@property
	def double(self):
		return self.count * 2

	def greeting(self):
		return f"Hi {self.user['name']}"

	def plus(self, a, b):
		return a + b
"""


def test_values_from_state_properties_attributes_and_helpers(tmp_path):

	module = component(tmp_path, "from markupsafe import Markup\n" + WIDGET, """
		<Widget>{{ count }}|{{ double }}|{{ label }}|{{ safe }}|{{ nothing }}|{{ greeting }}|{{ user.name }}|{{ user["name"] }}|{{ user.tags[1] }}|{{ user.missing }}|{{ plus(count, 2) }}|{{ plus("a", 'b') }}|{{ not nothing }}</Widget>
	""")
	html = inner(html_of(serve(tmp_path, module.Widget)), "Widget")

	assert html == "3|6|&lt;b&gt;bold&lt;/b&gt;|<i>ok</i>||Hi Ada|Ada|Ada|y||5|ab|True"


def test_an_unknown_name_says_where_and_suggests(tmp_path):

	module = component(tmp_path, WIDGET.replace("class Widget", "from markupsafe import Markup\n\n\nclass Widget"), "<Widget>\n\t<p>{{ cuont }}</p>\n</Widget>")
	app = serve(tmp_path, module.Widget)

	with pytest.raises(TemplateError) as error:
		app.test_page("/")

	message = str(error.value)
	assert "widget.html:2:5" in message and "Widget has no 'cuont'" in message
	assert "Did you mean 'count'?" in message and "Available: count, double, greeting" in message


def test_an_unknown_attribute_of_an_object_is_an_error(tmp_path):

	module = component(tmp_path, "class Widget(t.div):\n\tpoint = 1j\n", "<Widget>{{ point.imagx }}</Widget>")

	with pytest.raises(TemplateError, match=r"complex has no attribute 'imagx'.*Did you mean 'imag'"):
		serve(tmp_path, module.Widget).test_page("/")


def test_values_in_script_style_and_textarea(tmp_path):

	module = component(tmp_path, "class Widget(t.div):\n\tdata = {'a': '</script>'}\n\tcolor = 'red'\n\ttext = '<x>'\n", """
		<Widget><script>const data = {{ data }};</script><style>p { color: {{ color }}; }</style><textarea>{{ text }}</textarea></Widget>
	""")
	html = inner(html_of(serve(tmp_path, module.Widget)), "Widget")

	assert 'const data = {"a": "\\u003c/script\\u003e"};' in html
	assert "p { color: red; }" in html
	assert "<textarea>&lt;x&gt;</textarea>" in html


# Lists and conditions

def test_each_if_elif_else(tmp_path):

	module = component(tmp_path, """
		class Widget(t.div):

			items = State(["a", "b"])
			rows = [[1, 2], [3]]
			prices = {"tea": 2, "cake": 3}
			mode = State("one")

			def is_one(self):
				return self.mode == "one"

			def is_two(self):
				return self.mode == "two"
	""", """
		<Widget>
			<ul>
				<li each="item in items">{{ item }}</li>
				<li else>none</li>
			</ul>
			<p each="row in rows"><b each="cell in row">{{ cell }}</b></p>
			<i each="name, price in prices.items">{{ name }}={{ price }}</i>
			<i each="index, item in enumerate(items)">{{ index }}:{{ item }}</i>
			<template each="item in items"><dt>{{ item }}</dt><dd>-</dd></template>
			<p if="is_one">one</p>
			<p elif="is_two">two</p>
			<p else>other</p>
			<p if="not items">empty</p>
		</Widget>
	""")
	widget = module.Widget()
	app = serve(tmp_path, lambda: widget)
	html = inner(html_of(app), "Widget")

	assert "<ul>\n\t\t<li>a</li>\n\t\t<li>b</li>\n\t</ul>" in html
	assert "<p><b>1</b><b>2</b></p>\n\t<p><b>3</b></p>" in html
	assert "<i>tea=2</i>\n\t<i>cake=3</i>" in html
	assert "<i>0:a</i>\n\t<i>1:b</i>" in html
	assert "<dt>a</dt><dd>-</dd>\n\t<dt>b</dt><dd>-</dd>" in html
	assert "<p>one</p>" in html and "two" not in html and "other" not in html and "empty" not in html

	widget.items = []
	widget.mode = "two"
	html = inner(html_of(app), "Widget")
	assert "<ul>\n\t\t<li>none</li>\n\t</ul>" in html
	assert "<p>two</p>" in html and "<p>empty</p>" in html

	widget.mode = "three"
	assert "<p>other</p>" in inner(html_of(app), "Widget")


def test_each_with_if_filters(tmp_path):

	module = component(tmp_path, """
		class Widget(t.ul):
			items = [{"text": "a", "done": True}, {"text": "b", "done": False}]
	""", '<Widget><li each="item in items" if="item.done">{{ item.text }}</li></Widget>')

	assert inner(html_of(serve(tmp_path, module.Widget)), "Widget") == "<li>a</li>"


# Bound attributes

def test_bound_attributes(tmp_path):

	module = component(tmp_path, """
		class Widget(t.div):
			yes = True
			no = False
			none = None
			number = 0
			text = 'a"b'
			classes = {"on": True, "off": False}
			class_list = ["x", None, "y"]
			styles = {"font_weight": "bold", "color": None}
	""", """
		<Widget><input :disabled="yes" :hidden="no" :title="none" :value="number" :placeholder="text"><p class="base" :class="classes">1</p><p :class="class_list">2</p><p :class="text">3</p><p style="color: red;" :style="styles">4</p><p :class="none">5</p></Widget>
	""")
	html = inner(html_of(serve(tmp_path, module.Widget)), "Widget")

	assert '<input disabled value="0" placeholder="a&#34;b">' in html
	assert '<p class="base on">1</p>' in html
	assert '<p class="x y">2</p>' in html
	assert '<p class="a&#34;b">3</p>' in html
	assert '<p style="color: red; font-weight: bold">4</p>' in html
	assert "<p>5</p>" in html


# Events

LIST = """
class Widget(t.div):

	items = State(["a", "b", "c"])
	searched = State("")

	def remove(self, index):
		self.items = self.items[:index] + self.items[index + 1:]

	def rename(self, item, event):
		self.searched = f"{item}:{event.value}"

	def clear(self):
		self.items = []
"""

LIST_HTML = """
<Widget>
	<ul>
		<li each="index, item in enumerate(items)">{{ item }} <button on-click="remove(index)">x</button></li>
	</ul>
	<input on-input="rename(items[0], event)" debounce="250">
	<p>{{ searched }}</p>
	<button on-click="clear">clear</button>
</Widget>
"""


def test_events_with_values_per_item(tmp_path):

	module = component(tmp_path, LIST, LIST_HTML)
	page = serve(tmp_path, module.Widget).test_page("/")

	assert 'data-debounce-input="250"' in page.html

	# The second button removes the second item: each item's handler has its own index
	page.dispatch(page.find_all("li button")[1], "click")
	assert [li.text for li in page.find_all("li")] == ["a x", "c x"]

	page.type("input", "zz")
	assert page.text("p") == "a:zz"

	page.click("button", text="clear")
	assert page.find_all("li") == []


def test_event_ids_stay_the_same_across_renders(tmp_path):

	module = component(tmp_path, LIST, LIST_HTML)
	app = serve(tmp_path, module.Widget)
	page = app.test_page("/")

	before = [button.attrs["data-event-id"] for button in page.find_all("li button")]
	page.dispatch(page.find_all("li button")[2], "click")
	after = [button.attrs["data-event-id"] for button in page.find_all("li button")]

	assert after == before[:2]
	events = app.page_store.pages[page.page_id].events
	assert len(events) == 4  # two removes, the input and clear: the old ones were replaced


def test_an_event_needs_a_callable(tmp_path):

	module = component(tmp_path, "class Widget(t.div):\n\tlabel = 'x'\n", '<Widget><button on-click="label">x</button></Widget>')

	with pytest.raises(TemplateError, match="isn't a handler"):
		serve(tmp_path, module.Widget).test_page("/")


# Predictions

COUNTER = """
class Counter(t.div):

	count = State(0)

	def increment(self):
		self.count += 1
"""


def test_predictions_for_a_template_counter(tmp_path):

	module = component(tmp_path, COUNTER, '<Counter><p>Count: {{ count }}</p><button on-click="increment">+</button></Counter>', name="counter")
	app = serve(tmp_path, module.Counter)
	graph = json.loads(html_of(app).split("data-domino-predict>")[1].split("</script>")[0])

	assert len(graph["edges"]) == 1 and len(graph["states"]) == 2
	assert "<p>Count: 1</p>" in graph["states"][1]


def test_predictions_for_handlers_with_values(tmp_path):

	module = component(tmp_path, """
		class Tabs(t.div):

			active = State(0)
			names = ["One", "Two", "Three"]

			def select(self, index):
				self.active = index

			def is_active(self, index):
				return self.active == index
	""", """
		<Tabs><button each="index, name in enumerate(names)" on-click="select(index)" :aria-pressed="is_active(index)">{{ name }}</button></Tabs>
	""", name="tabs")
	app = serve(tmp_path, module.Tabs)
	graph = json.loads(html_of(app).split("data-domino-predict>")[1].split("</script>")[0])

	# Three states, each reachable from every other: the whole graph is shipped
	assert len(graph["states"]) == 3 and len(graph["edges"]) == 3
	assert "<button aria-pressed data-event-id" in html_of(app)


def test_a_handler_taking_the_event_is_not_predicted(tmp_path):

	from domino import optimistic

	module = component(tmp_path, LIST, LIST_HTML)
	app = serve(tmp_path, module.Widget)
	page = app.test_page("/")

	events = app.page_store.pages[page.page_id].events
	(rename,) = [callback for _, callback in events.values() if getattr(callback, "__name__", "") == "rename"]
	(remove, *_) = [callback for _, callback in events.values() if getattr(callback, "__name__", "") == "remove"]
	widget = remove.__self__

	assert optimistic.predictable_callback(widget, remove)
	assert not optimistic.predictable_callback(widget, rename)
	assert "takes the event" in optimistic.explain(widget, rename)


# Components as tags

CARDS = """
class Page(t.main):

	title = State("Hello")
	items = State(["a", "b"])

	def add(self, text):
		self.items = self.items + [text]


class Card(t.section):

	heading = None
	count = State(0)


class Adder(t.div):

	on_add = None

	def go(self):
		self.on_add("new")


class Plain(t.div):

	pass
"""

CARDS_HTML = """
<Page>
	<Card heading="Literal" class="extra" aria-label="card">
		<p>{{ title }}</p>
	</Card>
	<Card :heading="title" :count="items_count" />
	<Plain on-click="add_one" />
	<Adder on-add="add" />
	<ul><li each="item in items">{{ item }}</li></ul>
</Page>

<Card class="card">
	<h2>{{ heading }} ({{ count }})</h2>
	<slot>No content</slot>
</Card>

<Adder><button on-click="go">add</button></Adder>

<Plain>plain</Plain>
"""


def test_component_tags_props_children_and_slots(tmp_path):

	module = component(tmp_path, CARDS + "\n\nPage.items_count = property(lambda self: len(self.items))\nPage.add_one = lambda self: self.add('one')\n", CARDS_HTML, name="cards")
	page = serve(tmp_path, module.Page).test_page("/")
	cards = page.find_all("section")

	# Literal attributes and bound values become props; class adds to the definition's
	assert cards[0].attrs["class"] == "Card card extra" and cards[0].attrs["aria-label"] == "card"
	assert page.text("section h2") == "Literal (0)"
	# What's between <Card> and </Card> is where Card's <slot> is; without any, the slot's own
	assert cards[0].text == "Literal (0) Hello"
	assert cards[1].text == "Hello (2) No content"


def test_a_child_calls_its_parents_handler(tmp_path):

	module = component(tmp_path, CARDS + "\n\nPage.items_count = property(lambda self: len(self.items))\nPage.add_one = lambda self: self.add('one')\n", CARDS_HTML, name="cards")
	page = serve(tmp_path, module.Page).test_page("/")

	# Adder declares on_add, so it's the parent's handler, which the child calls
	page.click("button", text="add")
	assert [li.text for li in page.find_all("li")] == ["a", "b", "new"]

	# Plain doesn't declare on_click: it's a DOM event on Plain's element
	page.click(".Plain")
	assert [li.text for li in page.find_all("li")] == ["a", "b", "new", "one"]


def test_an_unknown_component_suggests_names(tmp_path):

	module = component(tmp_path, COUNTER, "<Counter><Countr /></Counter>", name="counter")

	with pytest.raises(TemplateError) as error:
		serve(tmp_path, module.Counter).test_page("/")

	assert "counter.html:1:10" in str(error.value)
	assert "<Countr> isn't a component Domino knows" in str(error.value) and "Did you mean 'Counter'?" in str(error.value)


def test_python_composition_passes_props_and_handlers(tmp_path):

	module = component(tmp_path, """
		class Tasks(t.div):

			items = State([])

			def render(self):
				return [Form(on_add=self.add), List(items=self.items, label=f"{len(self.items)} tasks")]

			def add(self, text):
				self.items = self.items + [text]


		class Form(t.form):

			on_add = None

			def submit(self, event):
				self.on_add(event.form["text"])


		class List(t.div):

			items = None
			label = ""
	""", """
		<Form on-submit="submit"><input name="text"><button>Add</button></Form>
		<List><p>{{ label }}</p><ul><li each="item in items">{{ item }}</li></ul></List>
	""", name="tasks")
	page = serve(tmp_path, module.Tasks).test_page("/")

	page.fill("input", "milk")
	page.click("button", text="Add")

	assert page.text("li") == "milk" and page.text("p") == "1 tasks"
	# A list isn't an HTML attribute
	assert "items=" not in page.html


def test_the_definitions_attributes_go_on_the_element(tmp_path):

	module = component(tmp_path, """
		class Box(t.div):

			open = State(False)

			def state(self):
				return "open" if self.open else None

			def toggle(self):
				self.open = not self.open
	""", '<Box class="box" role="region" :data-state="state" on-click="toggle">x</Box>', name="box")
	widget = module.Box(class_="mine", role="group")
	page = serve(tmp_path, lambda: widget).test_page("/")

	box = page.find(".Box")
	assert box.attrs["class"] == "Box box mine"
	# What the Python side set wins
	assert box.attrs["role"] == "group" and "data-state" not in box.attrs

	page.click(".Box")
	assert page.find(".Box").attrs["data-state"] == "open"
	page.click(".Box")
	assert "data-state" not in page.find(".Box").attrs


# Finding definitions

def test_definitions_are_found_anywhere_in_the_app(tmp_path):

	write(tmp_path / "parts" / "deep" / "misc.html", "<Badge><b>{{ text }}</b></Badge>")
	module = import_file(write(tmp_path / "elsewhere.py", "import domino.tags as t\n\n\nclass Badge(t.span):\n\ttext = 'new'\n"))

	app = serve(tmp_path, module.Badge)

	assert app.template_finder.definitions == {"Badge": [str(tmp_path / "parts" / "deep" / "misc.html")]}
	assert "<b>new</b>" in app.test_page("/").html


def test_a_duplicate_definition_fails_at_startup_naming_both(tmp_path):

	write(tmp_path / "a" / "one.html", "<Badge>1</Badge>")
	write(tmp_path / "b" / "two.html", "<Badge>2</Badge>")

	with pytest.raises(TemplateError) as error:
		Domino("app", root_path=str(tmp_path))

	assert "<Badge> is defined in more than one file" in str(error.value)
	assert os.path.join("a", "one.html") in str(error.value) and os.path.join("b", "two.html") in str(error.value)


def test_the_template_next_to_the_module_wins_for_two_classes_with_one_name(tmp_path):

	write(tmp_path / "a" / "badge.html", "<Badge>from a</Badge>")
	write(tmp_path / "b" / "badge.html", "<Badge>from b</Badge>")
	first = import_file(write(tmp_path / "a" / "badge.py", "import domino.tags as t\n\n\nclass Badge(t.span):\n\tpass\n"))
	second = import_file(write(tmp_path / "b" / "badge.py", "import domino.tags as t\n\n\nclass Badge(t.span):\n\tpass\n"))

	app = serve(tmp_path, lambda: t.div() [first.Badge(), second.Badge()])
	html = app.test_page("/").html

	assert ">from a</span>" in html and ">from b</span>" in html


def test_markup_outside_a_definition_is_an_error(tmp_path):

	write(tmp_path / "components" / "cards.html", "<Card>card</Card>\n<p>stray</p>\n")

	with pytest.raises(TemplateError) as error:
		Domino("app", root_path=str(tmp_path))

	assert "cards.html:2:1" in str(error.value) and "<p> is outside a component definition" in str(error.value)


def test_a_definition_twice_in_one_file(tmp_path):

	write(tmp_path / "cards.html", "<Card>1</Card>\n<Card>2</Card>")

	with pytest.raises(TemplateError, match="cards.html:2:1: <Card> is defined twice in this file"):
		Domino("app", root_path=str(tmp_path))


def test_a_self_closing_definition_explains(tmp_path):

	write(tmp_path / "cards.html", "<Card />")

	with pytest.raises(TemplateError, match="defines Card, but has no markup"):
		Domino("app", root_path=str(tmp_path))


def test_a_file_next_to_the_module_without_the_class_says_so(tmp_path):

	module = component(tmp_path, "class Widget(t.div):\n\tpass\n", "<Widgt>x</Widgt>")

	with pytest.raises(TemplateError) as error:
		serve(tmp_path, module.Widget).test_page("/")

	assert "widget.html defines Widgt, not Widget" in str(error.value)
	assert "Did you mean to name <Widgt> Widget?" in str(error.value)


def test_a_definition_without_a_class_warns(tmp_path, caplog):

	module = component(tmp_path, COUNTER, "<Counter>{{ count }}</Counter>\n<Countre>typo</Countre>", name="counter")

	with caplog.at_level(logging.WARNING):
		serve(tmp_path, module.Counter).test_page("/")

	assert "defines <Countre>, but no component class is called Countre (did you mean Counter?)" in caplog.text


def test_a_component_used_by_name_is_imported_from_next_to_its_definition(tmp_path, monkeypatch):

	write(tmp_path / "components" / "__init__.py", "")
	write(tmp_path / "components" / "gadget_dt.py", "import domino.tags as t\n\n\nclass GadgetDt(t.span):\n\tpass\n")
	write(tmp_path / "components" / "gadget_dt.html", "<GadgetDt>gadget</GadgetDt>")
	write(tmp_path / "pages" / "index.html", "<main><GadgetDt /></main>")
	monkeypatch.syspath_prepend(str(tmp_path))
	monkeypatch.delitem(sys.modules, "components", raising=False)

	try:
		app = make_app(tmp_path)
		assert ">gadget</span>" in app.test_page("/").html
	finally:
		for name in [name for name in sys.modules if name == "components" or name.startswith("components.")]:
			del sys.modules[name]


# Pages

def test_a_template_in_pages_is_a_page_inside_the_layouts(tmp_path):

	write(tmp_path / "pages" / "about.html", "<h1>About</h1>")
	write(tmp_path / "pages" / "users" / "[name].html", "<h1>User {{ name }}</h1>")
	write(tmp_path / "pages" / "layout.py", """
		import domino.tags as t
		from domino.components import Document


		def layout(content):
			return Document(title="Site") [t.nav() ["nav"], content]
	""")
	app = make_app(tmp_path)

	about = app.test_page("/about")
	assert about.text("title") == "Site" and about.text("nav") == "nav" and about.text("h1") == "About"
	assert app.test_page("/users/ada").text("h1") == "User ada"


def test_a_meteor_style_index_html(tmp_path):

	module = import_file(write(tmp_path / "components" / "counter.py", "import domino.tags as t\nfrom domino import State\n\n\n" + COUNTER))
	write(tmp_path / "components" / "counter.html", '<Counter><p>{{ count }}</p><button on-click="increment">+</button></Counter>')
	write(tmp_path / "pages" / "index.html", """
		<head>
			<title>Meteor style</title>
		</head>
		<body>
			<Counter />
		</body>
	""")
	app = make_app(tmp_path)
	assert module.Counter

	page = app.test_page("/")
	assert html_of(app).startswith("<!DOCTYPE html>\n<html data-domino-page=")
	assert page.text("title") == "Meteor style"

	page.click("button")
	assert page.text(".Counter p") == "1"


def test_template_from_a_route_finds_components_in_the_calling_module(tmp_path):

	module = import_file(write(tmp_path / "widgets.py", "import domino.tags as t\nfrom domino import State\n\n\n" + COUNTER + "\n\tdef render(self):\n\t\treturn [t.p() [f'Count {self.count}']]\n"))
	write(tmp_path / "home.html", "<main><h1>{{ title }}</h1><Counter /></main>")
	app = make_app(tmp_path)
	Counter = module.Counter  # noqa: F841 (found in this module's globals)

	@app.route("/")
	def index():

		return Document() [template("home.html", title="Home")]

	html = app.test_page("/").html

	assert "<h1>Home</h1>" in html and "Count 0" in html


def test_a_component_file_isnt_a_page(tmp_path):

	write(tmp_path / "cards.html", "<Card>x</Card>")
	app = make_app(tmp_path)

	@app.route("/")
	def index():

		return Document() [template("cards.html")]

	with pytest.raises(TemplateError, match="defines components"):
		app.test_page("/")


# Jinja, still

def test_which_files_are_jinja():

	source_format = dtemplates.source_format

	assert source_format("a.html", "<p>{{ name }}</p>") == "domino"
	assert source_format("a.html", "{% if x %}{% endif %}") == "jinja"
	assert source_format("a.html", "<p>{{ name|upper }}</p>") == "jinja"
	assert source_format("a.html", "<button {{ on(click=go) }}>") == "jinja"
	assert source_format("a.html", "{{ component(Counter) }}") == "jinja"
	assert source_format("a.html", '<a href="{{ url }}">') == "jinja"
	assert source_format("a.html", "{{ this.label }}") == "jinja"
	assert source_format("a.jinja", "<p>{{ name }}</p>") == "jinja"
	assert source_format("a.html", "{# jinja #}\n<p>{{ name }}</p>") == "jinja"
	assert source_format("a.html", "{# domino #}\n{% raw %}") == "domino"
	assert source_format("a.html", "<p>{{ name }}</p>", setting="jinja") == "jinja"


def test_jinja_pages_and_paired_templates_keep_working(tmp_path):

	write(tmp_path / "page.html", "{# jinja #}\n<main><h1>{{ title }}</h1>{{ component(Counter) }}</main>")
	module = component(tmp_path, COUNTER, "<p>{{ count }}</p><button {{ on(click=increment) }}>+</button>", name="counter")
	app = make_app(tmp_path)

	@app.route("/")
	def index():

		return Document() [template("page.html", title="Jinja", Counter=module.Counter)]

	page = app.test_page("/")
	assert page.text("h1") == "Jinja"
	page.click("button")
	assert page.text(".Counter p") == "1"


def test_the_jinja_setting_reads_every_page_template_as_jinja(tmp_path):

	write(tmp_path / "settings.json", '{"templates": "jinja"}')
	write(tmp_path / "page.html", "<p>{{ name }}</p>")
	app = make_app(tmp_path)

	with app.test_request_context():
		element = template("page.html", name="x")

	assert type(element).__name__ == "JinjaTemplate"


# Compiled once

def test_each_file_is_parsed_once(tmp_path):

	module = component(tmp_path, COUNTER, '<Counter><p>{{ count }}</p><button on-click="increment">+</button></Counter>', name="counter")
	app = serve(tmp_path, module.Counter)

	page = app.test_page("/")
	parses = dtemplates.stats["parses"]
	for _ in range(3):
		page.click("button")
	app.test_page("/")

	assert dtemplates.stats["parses"] == parses
	assert page.text("p") == "3"


def test_edits_are_picked_up_while_debugging(tmp_path):

	module = component(tmp_path, COUNTER, "<Counter>old {{ count }}</Counter>", name="counter")
	app = serve(tmp_path, module.Counter)
	app.debug = True
	app.testing = True

	assert "old 0" in app.test_page("/").html

	path = tmp_path / "components" / "counter.html"
	path.write_text("<Counter>new {{ count }}</Counter>", encoding="utf-8")
	later = time.time() + 5
	os.utime(path, (later, later))

	assert "new 0" in app.test_page("/").html


def test_hot_reloading_forgets_parsed_files(tmp_path):

	from domino import hot

	module = component(tmp_path, COUNTER, "<Counter>{{ count }}</Counter>", name="counter")
	app = serve(tmp_path, module.Counter)
	app.test_page("/")

	path = str(tmp_path / "components" / "counter.html")
	assert path in dtemplates._compiled

	hot.forget_caches(app, {path})

	assert path not in dtemplates._compiled and app.template_finder.stale
	write(tmp_path / "components" / "extra.html", "<Extra>x</Extra>")
	assert "Extra" in app.template_finder.current_definitions()


# The scaffold

def test_the_scaffold_uses_templates(tmp_path):

	from domino import cli

	cli.create(str(tmp_path / "site"))
	html = (tmp_path / "site" / "components" / "tasks.html").read_text()

	assert "<TaskForm on-submit=\"submit\">" in html and '<li each="task in tasks">{{ task.text }}</li>' in html
	assert dtemplates.parse_file(str(tmp_path / "site" / "components" / "tasks.html")).definitions.keys() == {"TaskForm", "TaskList", "NoTasks"}
	assert "def render" in (tmp_path / "site" / "components" / "tasks.py").read_text()


# as=

def test_as_picks_the_components_element(tmp_path):

	module = component(tmp_path, "class Sidebar(t.div):\n\tpass\n", '<Sidebar as="aside" class="w-64 border-r"><nav>links</nav></Sidebar>', name="sidebar")
	html = html_of(serve(tmp_path, module.Sidebar))

	assert '<aside class="Sidebar w-64 border-r" id="' in html and "<nav>links</nav></aside>" in html
	assert " as=" not in html


@pytest.mark.parametrize("source, message", [
	('<Sidebar :as="kind">x</Sidebar>', "can't be bound"),
	('<Sidebar as="Aside">x</Sidebar>', "names the HTML element"),
])
def test_as_takes_an_element_name(tmp_path, source, message):

	path = write(tmp_path / "sidebar.html", source)

	with pytest.raises(TemplateError, match=message):
		dtemplates.parse_file(str(path))


def test_as_and_a_tag_set_by_the_class_must_agree(tmp_path):

	# A tag set on the class (the Component base's `tag = "section"`) is what as= is checked against
	module = component(tmp_path, "class Sidebar(t.div):\n\tpass\n", '<Sidebar as="aside">x</Sidebar>', name="sidebar")
	sidebar = module.Sidebar()
	module.Sidebar.tag = "section"

	assert dtemplates._declared_tag(module.Sidebar) == "section"
	with pytest.raises(TemplateError, match='makes it an <aside>, but the class Sidebar sets tag = "section"'):
		dtemplates.render_component(sidebar, str(tmp_path / "components" / "sidebar.html"))
