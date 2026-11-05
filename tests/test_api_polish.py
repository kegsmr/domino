"""The polished Python API: class attributes are Python (HTML attributes come from keywords,
configure() and `attrs`), props, the children syntax, (handler, *args) handlers, components that
are live because they're refreshed, the debug warning for plain attributes, imports, events bound
in init(), configure() in render() with predictions, and whitespace around inline elements."""

import functools
import importlib
import json
import logging
import sys
import warnings

import pytest

import domino
import domino.tags as t
from domino import Collection, Component, Document, Domino, State
from domino._core import Element


def render(element):

	return element._render(indent="")


def serve(component, debug=False):
	"""An app showing `component` on /, and a simulated browser on it."""

	app = Domino(__name__)
	app.debug = debug

	@app.route("/")
	def index():
		return Document() [component]

	return app, app.test_page("/")


def page_html(app):
	"""The HTML of / as the server sends it."""

	return app.test_client().get("/").get_data(as_text=True)


def predictions_in(html):

	script = html.split("data-domino-predict>")[1].split("</script>")[0]
	return json.loads(script)


def deprecations(caught):

	return [str(warning.message) for warning in caught if issubclass(warning.category, DeprecationWarning)]


# 1. Class attributes are Python; HTML attributes are explicit


def test_plain_class_attributes_are_not_html_attributes():

	class TodoInput(t.div):

		label = "What needs doing?"
		items = []
		limit = 3
		renders = []
		client = False
		live = False
		optimistic = False
		optimistic_states = 4
		css = {"color": "red"}

	html = render(TodoInput())

	for name in (" label=", " items=", " limit=", " renders=", " client=", " live", " optimistic", " css="):
		assert name not in html


def test_attrs_declares_default_html_attributes_and_subclasses_add_to_them():

	class List(t.ul):

		attrs = {"role": "list", "data_kind": "plain"}

	class Tasks(List):

		attrs = {"data_kind": "tasks", "aria_label": "Tasks"}
		placeholder = "a setting, not an attribute"

	html = render(Tasks())

	assert 'role="list"' in html
	assert 'data-kind="tasks"' in html
	assert 'aria-label="Tasks"' in html
	assert "placeholder" not in html
	# Keyword arguments and configure() win over attrs
	assert 'role="tree"' in render(Tasks(role="tree"))


def test_html_looking_class_attributes_are_python_too():

	with warnings.catch_warnings(record=True) as caught:
		warnings.simplefilter("always")

		class Card(t.html):

			lang = "en"
			title = "Tasks"  # a setting the component shows itself

			def render(self):
				return [t.h2 [self.title]]

	assert deprecations(caught) == []
	html = render(Card())
	assert "lang=" not in html and "title=" not in html
	assert "<h2>Tasks</h2>" in html


def test_props_are_plain_python_values_set_from_keyword_arguments():

	added = []

	class TaskList(Component):

		items = []
		title = "Tasks"
		on_add = None
		count = State(1)

		def render(self):
			return [t.h2 [self.title], t.ul [[t.li [item] for item in self.items]], t.p [self.count]]

	tasks = TaskList(items=["a", "b"], title="Mine", on_add=added.append, count=5, id="tasks", data_x="1")

	assert tasks.items == ["a", "b"]
	tasks.on_add("x")  # the parent's handler
	assert added == ["x"]
	assert tasks.count == 5
	assert TaskList().items == [] and TaskList().count == 1
	html = render(tasks)
	assert "<h2>Mine</h2>" in html and "<li>a</li>" in html and "<p>5</p>" in html
	# Keywords that aren't props are HTML attributes (and on_<event> handlers)
	assert 'id="tasks"' in html and 'data-x="1"' in html
	assert "on-add" not in html and "data-event-id" not in html
	assert "items=" not in html and "title=" not in html


def test_a_child_calls_its_parents_handler():

	class AddButton(Component):

		text = ""
		on_add = None

		def render(self):
			return [t.button(on_click=(self.on_add, self.text)) [f"Add {self.text}"]]

	class Shopping(Component):

		items = State([])

		def render(self):
			return [
				AddButton(text="milk", on_add=self.add),
				AddButton(text="eggs", on_add=self.add),
				t.ul [[t.li [item] for item in self.items]],
			]

		def add(self, item):
			self.items = self.items + [item]

	_, page = serve(Shopping())
	page.click("button", text="Add eggs")
	page.click("button", text="Add milk")

	assert [li.text for li in page.find_all("li")] == ["eggs", "milk"]


def test_forms_settings_need_no_option_wrapper():

	from domino import forms

	class Join(forms.Form):

		name = forms.Text()
		submit_text = "Join"

	assert "Join</button>" in render(Join())
	assert "Sign up</button>" in render(Join(submit_text="Sign up"))
	assert "submit-text" not in render(Join())


# 2. Children


def test_tags_take_children_without_a_call():

	assert render(t.div ["hi"]) == render(t.div() ["hi"]) == '<div>hi</div>'
	assert render(t.ul [t.li ["a"], t.li ["b"]]) == "<ul><li>a</li><li>b</li></ul>"

	class Card(Component):
		pass

	assert render(Card ["x"]).endswith(">x</div>")


def test_lists_tuples_and_generators_are_flattened_and_none_skipped():

	items = ["a", "b"]

	expected = "<ul><li>a</li><li>b</li></ul>"
	assert render(t.ul [[t.li [item] for item in items]]) == expected
	assert render(t.ul [(t.li [item] for item in items)]) == expected
	assert render(t.ul [[t.li ["a"]], (t.li ["b"],)]) == expected
	assert render(t.ul [None, t.li ["a"], False, [None, [t.li ["b"]]], True]) == expected
	assert render(t.p [3, " items, ", 1.5, " each"]) == "<p>3 items, 1.5 each</p>"


def test_render_may_return_a_generator_and_cursors_are_iterated():

	notes = Collection()
	notes.insert({"text": "one"})
	notes.insert({"text": "two"})

	class Notes(t.ul):

		def render(self):
			return (t.li [note["text"]] for note in notes.find())

	class Cursor(t.ul):

		def render(self):
			return [t.li [note["text"]] for note in notes.find()]

	assert "<li>one</li><li>two</li>" in render(Notes())
	assert "<li>one</li><li>two</li>" in render(Cursor())


def test_old_children_styles_still_work_with_deprecation_warnings():

	class Old(t.div):

		def render(self):
			self([t.p ["old"]])
			return self

	with warnings.catch_warnings(record=True) as caught:
		warnings.simplefilter("always")
		html = render(Old())
		called = render(t.ul()([t.li ["a"]]))
		imperative = t.div()
		t.h1(imperative, "Title")
		button = t.button() ["Go"]
		button.bind("click", lambda: None)

	assert "<p>old</p>" in html
	assert called == "<ul><li>a</li></ul>"
	assert render(imperative) == "<div><h1>Title</h1></div>"
	assert "data-event-id" in render(button)

	messages = deprecations(caught)
	assert any("return the children from render()" in message for message in messages)
	assert any("write t.ul(...) [children]" in message for message in messages)
	assert any("t.h1(parent, ...) is deprecated" in message for message in messages)
	assert any('write on_click=callback' in message for message in messages)
	# Each points at the line that uses the old style, not at Domino
	assert all(warning.filename == __file__ for warning in caught if issubclass(warning.category, DeprecationWarning))


# 3. Handlers with arguments


class RemovableList(Component):

	items = State(["a", "b", "c", "d"])

	def render(self):
		return [
			t.ul [[
				t.li [item, " ", t.button(on_click=(self.remove, index)) [f"Remove {item}"]]
				for index, item in enumerate(self.items)
			]]
		]

	def remove(self, index):
		self.items = self.items[:index] + self.items[index + 1:]


def test_tuple_handlers_get_their_arguments_in_loops():

	_, page = serve(RemovableList())

	page.click("button", text="Remove b")
	assert [li.text.split()[0] for li in page.find_all("li")] == ["a", "c", "d"]
	page.click("button", text="Remove d")
	assert [li.text.split()[0] for li in page.find_all("li")] == ["a", "c"]


def test_tuple_handlers_get_the_event_after_their_arguments_if_they_take_it():

	got = []

	class Picker(t.div):

		def render(self):
			return [
				t.button(on_click=(self.pick, "left")) ["Left"],
				t.button(on_click=functools.partial(self.pick, "right")) ["Right"],
				t.button(on_click=(self.plain, 1, 2)) ["Plain"],
			]

		def pick(self, side, event):
			got.append((side, event.type))

		def plain(self, a, b):
			got.append(a + b)

	_, page = serve(Picker())
	page.click("button", text="Left")
	page.click("button", text="Right")
	page.click("button", text="Plain")

	assert got == [("left", "click"), ("right", "click"), 3]


def test_tuple_handlers_are_predicted_like_lambdas():

	app, _ = serve(RemovableList())
	graph = predictions_in(page_html(app))

	# Each button leads to the list without its item, shown at once
	assert len(graph["edges"][0]) == 4
	first = graph["edges"][0]
	states = graph["states"]
	shown = [states[index] if isinstance(states[index], str) else None for index in first.values()]
	assert any(html and "Remove a" not in html and "Remove b" in html for html in shown)


def test_tuple_handlers_that_do_more_are_not_predicted_and_say_why():

	from domino import _optimistic as optimistic

	saved = Collection()

	class Saver(t.div):

		count = State(0)

		def render(self):
			return [t.button(on_click=(self.save, 1)) ["Save"]]

		def save(self, number):
			saved.insert({"number": number})

	component = Saver()
	app, _ = serve(component)

	assert "data-domino-predict" not in page_html(app)
	reason = optimistic.explain(component, functools.partial(component.save, 1))
	assert "save()" in reason and "saved.insert" in reason


# 4. Fewer concepts


LIVE_MODULE = '''
import domino.tags as t


class Clock(t.div):

	def render(self):
		return [t.p ["tick"]]


class Quiet(t.div):

	def render(self):
		return [t.p ["quiet"]]


class Ticker(t.div):

	def render(self):
		return [t.p ["ticker"]]

	def tick(self):
		self.refresh()


clock = Clock()


def tick():
	clock.refresh()
'''


def test_components_their_module_refreshes_are_live_without_saying_so(tmp_path, monkeypatch):

	(tmp_path / "polish_live_module.py").write_text(LIVE_MODULE)
	monkeypatch.syspath_prepend(str(tmp_path))
	module = importlib.import_module("polish_live_module")
	try:
		assert module.clock.is_live()
		assert module.Ticker().is_live()
		assert not module.Quiet().is_live()

		app, page = serve(module.clock)
		assert "data-live" in page.html
		assert len(app.page_store.pages) == 1  # kept, for the pushes
	finally:
		sys.modules.pop("polish_live_module", None)


def test_refresh_makes_a_component_class_live_and_pushes_without_live_true():

	class Status(t.div):

		text = "starting"

		def render(self):
			return [t.p [self.text]]

	assert not Status().is_live()
	status = Status()
	status.refresh()  # before any page shows it
	assert Status().is_live()

	app, page = serve(status)
	assert "data-live" in page.html

	status.text = "ready"
	status.refresh()
	page.sync()
	assert page.text("p") == "ready"


def test_live_false_and_live_true_still_decide():

	class Never(t.div):

		live = False

		def render(self):
			return ["x"]

	class Always(t.div):

		live = True

		def render(self):
			return ["x"]

	never = Never()
	never.refresh()

	assert not never.is_live()
	assert Always().is_live()


class PlainCounter(t.div):

	count = 0

	def render(self):
		return [
			t.p [f"Count: {self.count}"],
			t.button(on_click=lambda: self.increment()) ["lambda"],
			t.button(on_click=self.increment) ["method"],
		]

	def increment(self):
		self.count += 1


def test_debug_warns_when_a_plain_attribute_changes_and_nothing_re_renders(caplog):

	_, page = serve(PlainCounter(), debug=True)

	with caplog.at_level(logging.WARNING):
		page.click("button", text="lambda")

	(message,) = [record.getMessage() for record in caplog.records if "isn't a State" in record.getMessage()]
	assert message.startswith("PlainCounter.count changed in lambda (test_api_polish.py:")
	assert message.endswith(" but isn't a State, so the page didn't update — use count = State(0)")
	assert page.text("p") == "Count: 0"


def test_no_warning_when_the_component_is_re_rendered_or_outside_debug(caplog):

	_, page = serve(PlainCounter(), debug=True)
	with caplog.at_level(logging.WARNING):
		page.click("button", text="method")  # re-renders its component, so it shows
	assert "isn't a State" not in caplog.text
	assert page.text("p") == "Count: 1"

	_, page = serve(PlainCounter())
	with caplog.at_level(logging.WARNING):
		page.click("button", text="lambda")
	assert "isn't a State" not in caplog.text


def test_t_document_and_component_are_importable_from_domino():

	from domino import t as tags_module, Document as Doc, State as S, Collection as C, Component as Comp
	from domino import Document as OldDocument

	assert tags_module is t
	assert Doc is OldDocument
	assert (S, C) == (State, Collection)
	assert Comp is t.Component


def test_component_is_a_div_unless_it_says_otherwise():

	class Todo(Component):
		pass

	class Panel(Component):

		tag = "section"

	class Old(t.div):
		pass

	assert render(Todo()).startswith('<div class="Todo" id=')
	assert render(Panel()).startswith('<section class="Panel" id=')
	assert render(Old()).startswith('<div class="Old" id=')
	assert "Component" not in render(Todo())


def test_events_bound_in_init_survive_re_renders():

	class Clicky(t.button):

		count = State(0)

		def init(self):
			self.configure(on_click=self.clicked)

		def render(self):
			return [f"Clicked {self.count}"]

		def clicked(self):
			self.count += 1

	_, page = serve(Clicky())
	for _ in range(3):
		page.click("button")

	assert page.text("button") == "Clicked 3"


def test_on_click_given_by_a_parent_survives_the_childs_own_re_renders():

	picked = []

	class Item(t.li):

		hovered = State(False)

		def render(self):
			return [t.span ["hovered" if self.hovered else "item"], t.button(on_click=self.hover) ["hover"]]

		def hover(self):
			self.hovered = not self.hovered

	class List(t.ul):

		def init(self):
			self.item = Item(on_dblclick=lambda: picked.append(1))

		def render(self):
			return [self.item]

	_, page = serve(List())
	page.click("button", text="hover")  # the item re-renders on its own
	assert page.text("span") == "hovered"

	page.dispatch(page.find("li"), "dblclick")
	assert picked == [1]


def test_configure_in_render_keeps_the_real_state_after_predictions():

	class Disclosure(t.div):

		open = State(False)

		def render(self):
			self.configure(aria_expanded="true" if self.open else "false", class_="open" if self.open else None)
			return [t.button(on_click=self.toggle) ["Toggle"]]

		def toggle(self):
			self.open = not self.open

	component = Disclosure()
	app, page = serve(component)
	html = page_html(app)
	opening = html.split(f'id="{component.id()}"')[0].rsplit("<div", 1)[1]

	assert "data-domino-predict" in html  # the other state was rendered
	assert 'aria-expanded="false"' in opening
	assert "open" not in opening.split("class=")[1].split('"')[1]

	page.click("button")
	assert 'aria-expanded="true"' in page.html


def test_inline_elements_add_no_spaces_before_punctuation():

	html = t.footer [
		t.p ["Built with ", t.a(href="/") ["Domino"], "."],
		t.p ["Plain text"],
		t.div ["Text before a list", t.ul [t.li ["one"]]],
		t.pre ["  kept\n  as is"],
	]._render()

	assert '<p>Built with <a href="/">Domino</a>.</p>' in html
	# Blocks keep their structure, one element per line
	assert html.startswith("<footer>\n    <p>")
	assert "    <p>\n        Plain text\n    </p>\n" in html
	assert "    <div>\n        Text before a list\n        <ul>\n" in html
	assert "<pre>  kept\n  as is</pre>" in html
	assert "            <li>\n                one\n            </li>\n" in html
	# An inline element's content is on its line
	assert t.div [t.button(type="button") ["Save"]]._render() == '<div>\n    <button type="button">Save</button>\n</div>\n'
