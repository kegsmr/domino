import pytest

import domino.tags as t
from domino import Collection, Domino, State
from domino import Document
from domino.testing import DominoTestError


class Counter(t.div):

	count = State(0)


	def render(self):

		return [
			t.p(class_="count") [f"Current Count: {self.count}"],
			t.button(on_click=self.increment) ["Increment"],
			t.button(on_click=self.decrement) ["Decrement"],
		]


	def increment(self):

		self.count += 1


	def decrement(self):

		self.count -= 1


class Todo(t.div):

	items = State([])


	def render(self):

		return [
			t.form(on_submit=self.add) [
				t.input(name="text"),
				t.select(name="priority") [t.option(value="low") ["Low"], t.option(value="high") ["High"]],
				t.input(type="checkbox", name="urgent"),
				t.button(type="submit") ["Add"],
			],
			t.ul() ([
				t.li() [
					t.input(type="checkbox", on_change=lambda event, index=index: self.remove(index)),
					f" {text}",
				]
				for index, text in enumerate(self.items)
			]),
		]


	def add(self, event):

		text = event.form.get("text", "").strip()
		if text:
			urgent = "!" if event.form.get("urgent") else ""
			self.items = self.items + [f"{text} ({event.form['priority']}){urgent}"]


	def remove(self, index):

		self.items = self.items[:index] + self.items[index + 1:]


class Search(t.div):

	query = State("")


	def render(self):

		return [
			t.input(name="q", value=self.query, on_input=self.search),
			t.p(id="echo") [f"Searching for: {self.query}"],
		]


	def search(self, event):

		self.query = event.value


def make_app(component_class):

	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document() [component_class()]

	return app


def test_click_runs_the_handler_and_updates_the_page():

	page = make_app(Counter).test_page("/")

	assert page.status == 200
	assert page.text("p") == "Current Count: 0"

	page.click("button", text="Increment")
	page.click("button", text="Increment")
	page.click("button", text="Decrement")

	assert page.text("p.count") == "Current Count: 1"


def test_each_test_page_is_its_own_browser_tab():

	app = make_app(Counter)
	first = app.test_page()
	second = app.test_page()

	first.click("button", text="Increment")

	assert first.text("p") == "Current Count: 1"
	assert second.text("p") == "Current Count: 0"


def test_submit_button_sends_the_form_and_fields_reset_from_the_server():

	page = make_app(Todo).test_page()

	page.fill("input[name=text]", "Buy milk")
	page.fill("select[name=priority]", "high")
	page.check("input[name=urgent]")
	page.click("button", text="Add")

	assert page.text("ul") == "Buy milk (high)!"
	# The submitted form takes the server's state: empty again
	assert page.value("input[name=text]") == ""

	page.fill("input[name=text]", "Walk dog")
	page.submit()

	assert [item.text for item in page.find_all("li")] == ["Buy milk (high)!", "Walk dog (low)"]

	page.click("li input[type=checkbox]")

	assert [item.text for item in page.find_all("li")] == ["Walk dog (low)"]


def test_typing_fires_input_events():

	page = make_app(Search).test_page()

	page.type("input[name=q]", "domino")

	assert page.text("#echo") == "Searching for: domino"
	assert page.value("input") == "domino"


def test_changes_from_another_page_are_pushed():

	messages = Collection()

	class Chat(t.div):

		def render(self):
			return [
				t.ul() ([t.li() [message["text"]] for message in messages.find()]),
				t.form(on_submit=self.send) [t.input(name="text"), t.button() ["Send"]],
			]

		def send(self, event):
			messages.insert({"text": event.form["text"]})

	app = make_app(Chat)
	alice = app.test_page()
	bob = app.test_page()

	alice.fill("input", "hi bob").click("button")

	assert alice.text("ul") == "hi bob"
	bob.sync()
	assert bob.text("ul") == "hi bob"


def test_failures_are_test_failures_with_the_traceback():

	class Broken(t.div):

		def render(self):
			return [t.button(on_click=self.explode) ["Boom"]]

		def explode(self):
			raise ValueError("kaboom")

	app = make_app(Broken)
	app.debug = True
	page = app.test_page()

	with pytest.raises(DominoTestError, match="kaboom"):
		page.click("button")

	with pytest.raises(DominoTestError, match="No element matches button with text 'Nope'"):
		page.click("button", text="Nope")


def test_selectors():

	page = make_app(Todo).test_page()

	assert page.find("form input[name=text]").tag == "input"
	assert page.find("div form button").text == "Add"
	assert page.find_all("ul li") == []
	assert page.find("option[value=high]").text == "High"
	assert "<form" in page.html


def test_timers_can_be_run_now():

	class Clock(t.div):

		ticks = State(0)

		def render(self):
			self.after(1000, self.tick)
			return [t.p() [f"Ticks: {self.ticks}"]]

		def tick(self):
			self.ticks += 1

	app = make_app(Clock)
	page = app.test_page()
	page.run_timers().run_timers()

	assert page.text("p") == "Ticks: 2"
