"""Child components keep their State in a real browser when their parent renders again (see
tests/test_child_state.py). Skipped when Playwright isn't installed."""

import threading

import pytest

playwright = pytest.importorskip("playwright.sync_api")

from werkzeug.serving import make_server

import domino.tags as t
from domino import Domino, State
from domino.components import Document


class Counter(t.div):

	count = State(0)


	def add(self):

		self.count += 1


	def render(self):

		return [t.span(class_="real") [f"real {self.count}"], t.button(class_="r", on_click=self.add) ["+"]]


class Row(t.li):

	name = ""
	clicks = State(0)


	def click(self):

		self.clicks += 1


	def render(self):

		return [t.button(class_=f"row row-{self.name}", on_click=self.click) [f"{self.name} {self.clicks}"]]


class Parent(t.div):

	other = State(0)
	names = State(["a", "b", "c"])


	def bump(self):

		self.other += 1


	def reverse(self):

		self.names = list(reversed(self.names))


	def render(self):

		return [
			Counter(),
			t.button(class_="parent", on_click=self.bump) [f"parent {self.other}"],
			t.button(class_="reverse", on_click=self.reverse) ["reverse"],
			t.ul() ([Row(key=name, name=name) for name in self.names]),
		]


@pytest.fixture
def url():

	app = Domino(__name__)

	@app.route("/")
	def index():

		return Document(title="Child state") [Parent()]

	server = make_server("127.0.0.1", 0, app, threaded=True)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	yield f"http://127.0.0.1:{server.server_port}/"
	server.shutdown()


@pytest.fixture
def page():

	with playwright.sync_playwright() as p:
		browser = p.chromium.launch()
		page = browser.new_page()
		page.errors = []
		page.on("console", lambda message: message.type == "error" and page.errors.append(message.text))
		page.on("pageerror", lambda error: page.errors.append(str(error)))
		yield page
		browser.close()


def wait_text(page, selector, text, timeout=3000):

	page.wait_for_function(f"document.querySelector({selector!r}).textContent.trim() === {text!r}", timeout=timeout)


def test_a_child_keeps_its_state_when_the_parent_renders_again(url, page):

	page.goto(url)
	page.click(".r")
	wait_text(page, ".real", "real 1")
	page.click(".r")
	wait_text(page, ".real", "real 2")
	node = page.evaluate_handle("document.querySelector('.Counter')")

	page.click(".parent")
	wait_text(page, ".parent", "parent 1")
	assert page.inner_text(".real").strip() == "real 2"
	# The browser updated the same node in place
	assert page.evaluate("node => node === document.querySelector('.Counter')", node)

	page.click(".r")
	wait_text(page, ".real", "real 3")
	assert page.errors == []


def test_keyed_rows_keep_their_state_when_reordered(url, page):

	page.goto(url)
	page.click(".row-a")
	wait_text(page, ".row-a", "a 1")
	page.click(".row-c")
	page.click(".row-c")
	wait_text(page, ".row-c", "c 2")

	page.click(".reverse")
	page.wait_for_function("document.querySelector('.row').textContent.trim() === 'c 2'")
	assert page.eval_on_selector_all(".row", "rows => rows.map(row => row.textContent.trim())") == ["c 2", "b 0", "a 1"]
	assert page.errors == []


def test_instant_updates_keep_the_childs_state(url, page):

	page.goto(url)
	page.click(".r")
	page.click(".r")
	wait_text(page, ".real", "real 2")

	page.evaluate("Domino.enableLatencySim(1500)")

	# The parent's update shows before the server answers, with the child's State in it
	page.click(".parent")
	wait_text(page, ".parent", "parent 1", timeout=700)
	assert page.inner_text(".real").strip() == "real 2"

	# And the child's own update is still instant afterwards
	page.wait_for_function("!document.querySelector('[data-predicted]')", timeout=4000)
	page.click(".r")
	wait_text(page, ".real", "real 3", timeout=700)

	page.wait_for_function("!document.querySelector('[data-predicted]')", timeout=4000)
	page.evaluate("Domino.disableLatencySim()")
	assert page.inner_text(".real").strip() == "real 3"
	assert page.inner_text(".parent").strip() == "parent 1"
	assert page.errors == []


class Labelled(t.div):

	label = 0
	count = State(0)


	def add(self):

		self.count += 1


	def render(self):

		return [t.span(class_="labelled") [f"{self.label}: {self.count}"], t.button(class_="labelled-add", on_click=self.add) ["+"]]


class Passing(t.div):

	other = State(0)


	def bump(self):

		self.other += 1


	def render(self):

		return [Labelled(label=self.other), t.button(class_="passing", on_click=self.bump) [f"passing {self.other}"]]


@pytest.fixture
def passing_url():

	app = Domino(__name__)

	@app.route("/")
	def index():

		return Document(title="Passing") [Passing()]

	server = make_server("127.0.0.1", 0, app, threaded=True)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	yield f"http://127.0.0.1:{server.server_port}/"
	server.shutdown()


def test_a_guess_that_would_show_a_changed_child_wrong_waits_for_the_server(passing_url, page):

	page.goto(passing_url)
	page.click(".labelled-add")
	wait_text(page, ".labelled", "0: 1")

	page.evaluate("Domino.enableLatencySim(1000)")
	page.click(".passing")

	# The parent's guess has the child as it was ("1: 0"), and passes it a new label, so it isn't
	# shown: the server answers instead
	page.wait_for_timeout(400)
	assert page.inner_text(".labelled").strip() == "0: 1"
	wait_text(page, ".labelled", "1: 1", timeout=4000)
	assert page.inner_text(".passing").strip() == "passing 1"

	# With the server's answer, the parent's next click is instant again
	page.click(".passing")
	wait_text(page, ".labelled", "2: 1", timeout=700)
	page.wait_for_function("!document.querySelector('[data-predicted]')", timeout=4000)
	page.evaluate("Domino.disableLatencySim()")
	assert page.errors == []
