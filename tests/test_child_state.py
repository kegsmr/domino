"""A child component keeps its State while it's on screen: when its parent renders again, the child
the new render makes in the same place (or with the same key=) takes over the old one's State."""

import importlib.util
import json
import logging
import sys
import textwrap
import uuid

import domino.tags as t
from domino import Collection, Domino, State
from domino.components import Document


class Counter(t.div):

	count = State(0)


	def add(self, event=None):

		self.count += 1


	def render(self):

		return [t.span(class_="real") [f"real {self.count}"], t.button(class_="r", on_click=self.add) ["+"]]


class Parent(t.div):

	other = State(0)


	def bump(self, event=None):

		self.other += 1


	def render(self):

		return [Counter(), t.button(class_="parent", on_click=self.bump) ["re-render parent"]]


class Row(t.li):

	name = ""
	clicks = State(0)


	def click(self):

		self.clicks += 1


	def render(self):

		return [t.button(class_=f"row-{self.name}", on_click=self.click) [f"{self.name} {self.clicks}"]]


class KeyedList(t.ul):

	names = State(["a", "b", "c"])


	def render(self):

		return [Row(key=name, name=name) for name in self.names]


class UnkeyedList(t.ul):

	names = State(["a", "b", "c"])


	def render(self):

		return [Row(name=name) for name in self.names]


class Grandparent(t.div):

	other = State(0)


	def bump(self):

		self.other += 1


	def render(self):

		return [t.section() [Parent()], t.button(class_="grandparent", on_click=self.bump) [f"grandparent {self.other}"]]


def make_app(component, debug=False):
	"""An app showing `component` (a class: a new one per page; or one instance, for a test to change)."""

	app = Domino(__name__)
	app.debug = debug

	@app.route("/")
	def index():

		if isinstance(component, type):
			return Document() [component()]
		return Document() [component]

	return app


def rows(page):

	return [node.text for node in page.find_all("li button")]


def test_a_child_keeps_its_state_when_the_parent_renders_again():

	page = make_app(Parent).test_page("/")
	assert page.text(".real") == "real 0"

	page.click(".r")
	page.click(".r")
	assert page.text(".real") == "real 2"
	child_id = page.find(".Counter").attrs["id"]

	page.click(".parent")
	assert page.text(".real") == "real 2"
	# The same id, so the browser updates the same node
	assert page.find(".Counter").attrs["id"] == child_id

	# And the child still works after its parent rendered again
	page.click(".r")
	assert page.text(".real") == "real 3"


def test_grandchildren_keep_their_state_too():

	page = make_app(Grandparent).test_page("/")

	page.click(".r")
	page.click(".parent")
	page.click(".grandparent")

	assert page.text(".real") == "real 1"
	assert page.text(".grandparent") == "grandparent 1"


def test_a_keyed_list_keeps_each_rows_state_across_reorder_insert_and_delete():

	component = KeyedList()
	page = make_app(component).test_page("/")

	page.click(".row-a")
	page.click(".row-c")
	page.click(".row-c")
	assert rows(page) == ["a 1", "b 0", "c 2"]

	# Reorder
	set_names(page, component, ["c", "b", "a"])
	assert rows(page) == ["c 2", "b 0", "a 1"]

	# Insert, at the start
	set_names(page, component, ["d", "c", "b", "a"])
	assert rows(page) == ["d 0", "c 2", "b 0", "a 1"]

	# Delete
	set_names(page, component, ["d", "a"])
	assert rows(page) == ["d 0", "a 1"]

	# A row that comes back starts again
	set_names(page, component, ["d", "a", "c"])
	assert rows(page) == ["d 0", "a 1", "c 0"]


def test_an_unkeyed_list_matches_by_position_and_warns_while_debugging(caplog):

	from domino import core
	core._unkeyed_warned.clear()

	component = UnkeyedList()
	page = make_app(component, debug=True).test_page("/")

	page.click(".row-a")
	assert rows(page) == ["a 1", "b 0", "c 0"]

	# The same length: the first row keeps the first row's State, whatever its name
	with caplog.at_level(logging.WARNING):
		set_names(page, component, ["c", "b", "a"])
	assert rows(page) == ["c 1", "b 0", "a 0"]
	assert "without key=" not in caplog.text

	# Another length: warned, once
	with caplog.at_level(logging.WARNING):
		set_names(page, component, ["x", "c", "b", "a"])
		set_names(page, component, ["c", "b", "a"])
	assert rows(page) == ["c 1", "b 0", "a 0"]
	assert caplog.text.count("without key=") == 1
	assert "UnkeyedList renders a list of Row that went from 3 to 4" in caplog.text


def test_no_warning_outside_debug_mode(caplog):

	from domino import core
	core._unkeyed_warned.clear()

	component = UnkeyedList()
	page = make_app(component).test_page("/")

	with caplog.at_level(logging.WARNING):
		set_names(page, component, ["a", "b"])

	assert "without key=" not in caplog.text


notes = Collection()


class Live(t.div):

	count = State(0)


	def add(self):

		self.count += 1


	def render(self):

		return [t.p(class_="live") [f"{len(notes.find().fetch())} notes, {self.count}"], t.button(class_="live-add", on_click=self.add) ["+"]]


class LiveParent(t.div):

	other = State(0)


	def bump(self):

		self.other += 1


	def render(self):

		return [Live(), t.button(class_="parent", on_click=self.bump) [f"parent {self.other}"]]


def test_a_replaced_child_stops_updating_and_the_new_one_takes_over():

	page = make_app(LiveParent).test_page("/")
	page.click(".live-add")
	for _ in range(3):
		page.click(".parent")

	state = only_page(page)
	lives = [component for component in state.components if isinstance(component, Live)]
	# Only the one on screen is live; the ones it replaced are no longer subscribed
	assert len(lives) == 1

	notes.insert({"text": "hi"})
	page.sync()
	assert page.text(".live") == "1 notes, 1"


def test_a_child_passed_a_state_value_keeps_its_own_after_that():

	class Start(t.div):

		count = State(0)


		def add(self):

			self.count += 1


		def render(self):

			return [t.button(class_="start", on_click=self.add) [str(self.count)]]


	class Holder(t.div):

		other = State(0)


		def bump(self):

			self.other += 1


		def render(self):

			# count= is its starting value, like React's useState(initial)
			return [Start(count=10), t.button(class_="parent", on_click=self.bump) ["parent"]]


	page = make_app(Holder).test_page("/")
	page.click(".start")
	page.click(".parent")

	assert page.text(".start") == "11"


def test_children_a_template_makes_keep_their_state(tmp_path, forget_modules):

	(tmp_path / "components").mkdir()
	(tmp_path / "components" / "board.html").write_text(textwrap.dedent("""
		<component name="Board">
			<button class="parent" on-click="bump">parent {{ other }}</button>
			<ul>
				{{ for name in names }}
				<Item key="{{ name }}" name="{{ name }}" />
				{{ /for }}
			</ul>
		</component>
	"""), encoding="utf-8")
	(tmp_path / "components" / "board.py").write_text(textwrap.dedent("""
		import domino.tags as t
		from domino import State


		class Item(t.li):

			name = ""
			clicks = State(0)


			def click(self):

				self.clicks += 1


			def render(self):

				return [t.button(class_=f"row-{self.name}", on_click=self.click) [f"{self.name} {self.clicks}"]]


		class Board(t.div):

			other = State(0)
			names = State(["a", "b"])


			def bump(self):

				self.other += 1
				self.names = list(reversed(self.names))
	"""), encoding="utf-8")

	name = f"domino_child_state_{uuid.uuid4().hex[:8]}"
	spec = importlib.util.spec_from_file_location(name, tmp_path / "components" / "board.py")
	module = importlib.util.module_from_spec(spec)
	sys.modules[name] = module
	spec.loader.exec_module(module)

	try:
		app = Domino("app", root_path=str(tmp_path))
		app.testing = True

		@app.route("/")
		def index():

			return Document() [module.Board()]

		page = app.test_page("/")
		page.click(".row-b")
		page.click(".parent")

		assert rows(page) == ["b 1", "a 0"]
		assert page.text(".parent") == "parent 1"
	finally:
		forget_modules(tmp_path)


def test_the_parents_instant_update_shows_the_childs_state():

	parent = Parent()
	app = make_app(parent)
	client = app.test_client()
	html = client.get("/").get_data(as_text=True)
	page_id = html.split('data-domino-page="')[1].split('"')[0]
	page = app.page_store.pages[page_id]

	def click(name):
		event_id = next(event_id for event_id, (_, callback) in page.events.items() if callback.__name__ == name)
		return client.post("/_domino/events", json={"page_id": page_id, "event_id": event_id}).get_json()

	click("add")
	click("add")
	data = click("bump")

	assert "real 2" in data["html"].split("data-domino-predict>")[0]
	# Its prediction of the next bump (rendered ahead of time) keeps the child's State too
	graphs = [json.loads(part.split("</script>")[0]) for part in data["html"].split("data-domino-predict>")[1:]]
	states = [state for graph in graphs for state in graph["states"] if isinstance(state, str) and "re-render parent" in state]
	assert states and all("real 2" in state and "real 0" not in state for state in states)


def test_a_component_shown_on_several_pages_updates_its_children_on_all_of_them():

	parent = Parent()
	app = make_app(parent)
	first = app.test_page("/")
	first.click(".r")
	second = app.test_page("/")

	second.click(".r")
	first.sync()
	assert first.text(".real") == second.text(".real") == "real 2"

	first.click(".r")
	second.sync()
	assert first.text(".real") == second.text(".real") == "real 3"


class Many(t.div):

	other = State(0)
	optimistic = False


	def bump(self):

		self.other += 1


	def render(self):

		return [t.button(class_="parent", on_click=self.bump) [f"parent {self.other}"], t.ul() ([Row(key=index, name=str(index)) for index in range(50)])]


def test_rendering_the_parent_again_keeps_the_childrens_html_so_patches_stay_small():

	from domino.patches import COPY_COST, diff

	app = make_app(Many)
	client = app.test_client()
	html = client.get("/").get_data(as_text=True)
	page_id = html.split('data-domino-page="')[1].split('"')[0]
	page = app.page_store.pages[page_id]

	def bump():
		event_id = next(event_id for event_id, (_, callback) in page.events.items() if callback.__name__ == "bump")
		return client.post("/_domino/events", json={"page_id": page_id, "event_id": event_id}).get_json()["html"]

	first = bump()
	second = bump()

	# Only the parent's own line changed: the rows kept their ids, and so their HTML
	ops = diff(first, second)
	assert ops is not None
	assert sum(len(op) if isinstance(op, str) else COPY_COST for op in ops) < 100


# Helpers

def only_page(page):

	(state,) = page.app.page_store.pages.values()

	return state


def set_names(page, component, names):
	"""Change the list from outside an event (as another user's change would), then catch up."""

	component.names = names
	page.sync()
