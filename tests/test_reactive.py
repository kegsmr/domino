import gc
import threading

import pytest

import domino.tags as t
from domino import Collection, Domino, State, batch, wait
from domino.components import Document


def load(client, path="/"):

	html = client.get(path).get_data(as_text=True)
	page_id = html.split('data-domino-page="')[1].split('"')[0]
	return page_id, html


def click(client, page_id, event_id, data=None):

	return client.post("/_domino/events", json={"page_id": page_id, "event_id": event_id, "data": data})


# --- State ---------------------------------------------------------------

def test_reading_state_in_render_subscribes_and_marks_live():

	count = State(0)

	class Counter(t.div):

		def render(self):
			self([f"Count: {count.value}"])

	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document() [Counter()]

	client = app.test_client()
	page_id, html = load(client)

	assert "data-live" in html
	page = app.page_store.pages[page_id]

	count.value = 5

	(update,) = page.updates.values()
	assert "Count: 5" in update["html"]


def test_setting_the_same_value_does_not_rerender():

	count = State(1)
	renders = []

	class Counter(t.div):

		def render(self):
			renders.append(count.value)
			self([str(count.value)])

	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document() [Counter()]

	load(app.test_client())
	count.value = 1

	assert renders == [1]


def test_subscriptions_follow_what_the_last_render_read():

	show = State(True)
	detail = State("a")

	class Panel(t.div):

		def render(self):
			if show.value:
				self([detail.value])
			else:
				self(["hidden"])

	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document() [Panel()]

	client = app.test_client()
	page_id, _ = load(client)
	page = app.page_store.pages[page_id]

	show.value = False
	page.updates.clear()
	detail.value = "b"

	# The panel no longer reads `detail`, so changing it doesn't re-render the panel
	assert page.updates == {}


def test_reactive_component_without_events_stays_alive():

	count = State(0)

	class Counter(t.div):

		def render(self):
			self([f"Count: {count.value}"])

	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document() [Counter()]

	page_id, _ = load(app.test_client())
	gc.collect()
	count.value = 1

	assert "Count: 1" in list(app.page_store.pages[page_id].updates.values())[0]["html"]


# --- Collections -----------------------------------------------------------

def test_collection_crud_and_queries():

	people = Collection()
	ada = people.insert({"name": "Ada", "age": 36, "tags": ["math"]})
	people.insert({"name": "Alan", "age": 41, "tags": ["math", "crypto"]})
	people.insert({"name": "Grace", "age": 85, "address": {"city": "NYC"}})

	assert people.find_one({"_id": ada})["name"] == "Ada"
	assert [p["name"] for p in people.find({"age": {"$gt": 40}}, sort="age")] == ["Alan", "Grace"]
	assert [p["name"] for p in people.find(sort=[("age", -1)], limit=2)] == ["Grace", "Alan"]
	assert people.count({"tags": "crypto"}) == 1
	assert people.count({"address.city": "NYC"}) == 1
	assert people.count({"$or": [{"name": "Ada"}, {"name": "Grace"}]}) == 2
	assert people.count({"address": {"$exists": False}}) == 2
	assert people.count({"name": {"$in": ["Ada", "Bob"]}}) == 1

	assert people.update({"name": "Ada"}, {"$inc": {"age": 1}, "$push": {"tags": "code"}}) == 1
	assert people.find_one({"name": "Ada"})["age"] == 37
	assert people.find_one({"name": "Ada"})["tags"] == ["math", "code"]
	assert people.update({"tags": "math"}, {"$set": {"field": "cs"}}, multi=True) == 2
	assert people.update({"name": "Grace"}, {"name": "Grace Hopper"}) == 1
	assert people.find_one({"name": "Grace Hopper"})["_id"]

	assert people.remove({"field": "cs"}) == 2
	assert people.count() == 1


def test_documents_returned_are_copies():

	notes = Collection()
	notes.insert({"text": "hi", "tags": []})

	note = notes.find_one()
	note["tags"].append("changed")

	assert notes.find_one()["tags"] == []


def test_duplicate_id_is_rejected():

	notes = Collection()
	notes.insert({"_id": "x"})

	with pytest.raises(ValueError):
		notes.insert({"_id": "x"})


def test_unsupported_operator_is_an_error():

	with pytest.raises(ValueError):
		Collection().find({"a": {"$regex": "x"}}).fetch()


# --- Across pages ------------------------------------------------------------

def make_chat_app():

	messages = Collection()

	class Chat(t.div):

		def render(self):
			self([
				t.ul()([t.li() [m["text"]] for m in messages.find(sort="n")]),
				form := t.form() [t.input(name="text")]
			])
			form.bind("submit", self.send)

		def send(self, event):
			messages.insert({"text": event.form["text"], "n": messages.count()})
			return self

	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document() [Chat()]

	return app, messages


def test_change_from_one_page_pushes_to_others_but_not_back():

	app, _ = make_chat_app()
	client = app.test_client()
	page_a, html_a = load(client)
	page_b, _ = load(client)
	submit = html_a.split('data-event-id="')[1].split('"')[0]

	response = click(client, page_a, submit, {"form": {"text": "hello"}}).get_json()
	wait()

	assert "hello" in response["html"]
	assert app.page_store.pages[page_a].updates == {}
	(update,) = app.page_store.pages[page_b].updates.values()
	assert "hello" in update["html"]


def test_many_changes_in_one_batch_render_once():

	count = State(0)
	renders = []

	class Counter(t.div):

		def render(self):
			renders.append(count.value)
			self([str(count.value)])

	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document() [Counter()]

	load(app.test_client())
	renders.clear()

	with batch():
		for value in range(1, 11):
			count.value = value

	assert renders == [10]


def test_concurrent_events_on_two_pages_do_not_deadlock():

	app, messages = make_chat_app()
	client = app.test_client()
	pages = [load(client) for _ in range(2)]
	submits = [html.split('data-event-id="')[1].split('"')[0] for _, html in pages]

	def send(page_id, event_id):
		local = app.test_client()
		for i in range(20):
			click(local, page_id, event_id, {"form": {"text": f"{page_id}-{i}"}})

	threads = [threading.Thread(target=send, args=(pages[i][0], submits[i])) for i in range(2)]
	for thread in threads:
		thread.start()
	for thread in threads:
		thread.join(timeout=10)

	assert not any(thread.is_alive() for thread in threads)
	assert messages.count() == 40
	wait()


def test_sender_does_not_wait_for_other_pages_to_update():

	import time

	count = State(0)

	class Slow(t.div):

		def render(self):
			if count.value:
				time.sleep(0.5)
			self([str(count.value)])

	class Button(t.div):

		def render(self):
			self([button := t.button() ["+"]])
			button.bind("click", self.click)

		def click(self):
			count.value += 1
			return self

	app = Domino(__name__)

	@app.route("/slow")
	def slow():
		return Document() [Slow()]

	@app.route("/button")
	def button():
		return Document() [Button()]

	client = app.test_client()
	slow_page, _ = load(client, "/slow")
	button_page, html = load(client, "/button")
	event_id = html.split('data-event-id="')[1].split('"')[0]

	start = time.perf_counter()
	assert click(client, button_page, event_id).status_code == 200
	took = time.perf_counter() - start
	wait()

	assert took < 0.4
	(update,) = app.page_store.pages[slow_page].updates.values()
	assert ">1<" in update["html"].replace("\n", "").replace(" ", "")
