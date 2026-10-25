import json
import re
import threading

import domino.tags as t
from domino import Domino
from domino.components import Document


class Counter(t.div):


	def __init__(self, *args, **kwargs):

		super().__init__(*args, **kwargs)

		self.count = 0


	def render(self):

		self([
			t.p() [
				f"Count: {self.count}"
			],
			button := t.button() [
				"+"
			]
		])

		button.bind("click", self.increment)


	def increment(self):

		self.count += 1

		return self


def make_app(counter=None):

	app = Domino(__name__)
	app.config["DOMINO_KEEPALIVE"] = 0.05

	@app.route("/")
	def index():
		return Document() [
			Counter() if counter is None else counter  # an empty element is falsy
		]

	return app


def load(client):

	html = client.get("/").get_data(as_text=True)
	return html.split('data-domino-page="')[1].split('"')[0]


def page(app, page_id):

	return app.page_store.pages[page_id]


def drain(page):

	return page.pull(page.stream, 0)


def test_refresh_pushes_rerendered_html_to_its_page():

	counter = Counter()
	app = make_app(counter)
	page_id = load(app.test_client())

	counter.count = 5
	counter.refresh()

	updates = drain(page(app, page_id))
	assert len(updates) == 1
	assert updates[0]["id"] == counter.id()
	assert "Count: 5" in updates[0]["html"]
	assert updates[0]["html"].startswith(f'<div class="Counter" id="{counter.id()}"')


def test_refresh_pushes_to_every_page_showing_the_component():

	counter = Counter()
	app = make_app(counter)
	client = app.test_client()
	page_a, page_b = load(client), load(client)

	counter.count = 2
	counter.refresh()

	for page_id in (page_a, page_b):
		updates = drain(page(app, page_id))
		assert len(updates) == 1
		assert "Count: 2" in updates[0]["html"]


def test_refresh_without_a_live_page_does_nothing():

	counter = Counter()

	counter.refresh()
	counter._render()  # outside a request: not on any page
	counter.refresh()

	assert len(counter.__pages__) == 0


def test_binds_during_refresh_land_on_the_page_with_stable_ids():

	counter = Counter()
	app = make_app(counter)
	client = app.test_client()
	html = client.get("/").get_data(as_text=True)
	page_id = html.split('data-domino-page="')[1].split('"')[0]
	event_id = html.split('data-event-id="')[1].split('"')[0]

	counter.refresh()
	counter.refresh()

	assert list(page(app, page_id).events) == [event_id]
	assert f'data-event-id="{event_id}"' in drain(page(app, page_id))[0]["html"]

	# The handler registered by the refresh still works
	response = client.post("/_domino/events", json={"page_id": page_id, "event_id": event_id})
	assert "Count: 1" in response.get_json()["html"]


def test_refresh_from_another_thread():

	counter = Counter()
	app = make_app(counter)
	page_id = load(app.test_client())

	counter.count = 7
	thread = threading.Thread(target=counter.refresh)
	thread.start()
	thread.join(5)

	assert "Count: 7" in drain(page(app, page_id))[0]["html"]


def test_stream_404s_for_unknown_page():

	app = make_app()
	client = app.test_client()

	assert client.get("/_domino/stream?page=nope").status_code == 404
	assert client.get("/_domino/stream").status_code == 404


def read_stream(response, count, timeout=5):

	# Read in a thread so a broken stream fails the test instead of hanging it
	chunks = []

	def read():
		for chunk in response.response:
			chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
			if len(chunks) == count:
				break

	thread = threading.Thread(target=read, daemon=True)
	thread.start()
	thread.join(timeout)
	assert not thread.is_alive(), f"stream stalled after {chunks!r}"
	response.close()

	return chunks


def test_stream_yields_pushed_updates_and_keepalives():

	counter = Counter()
	app = make_app(counter)
	client = app.test_client()
	page_id = load(client)

	response = client.get(f"/_domino/stream?page={page_id}", buffered=False)
	assert response.status_code == 200
	assert response.mimetype == "text/event-stream"
	assert response.headers["Cache-Control"] == "no-cache"
	assert response.headers["X-Accel-Buffering"] == "no"

	counter.count = 3
	counter.refresh()

	opened, update, keepalive = read_stream(response, 3)
	assert opened == ": open\n\n"
	assert update.startswith("data: ") and update.endswith("\n\n")
	data = json.loads(update[len("data: "):])
	assert data["id"] == counter.id()
	assert "Count: 3" in data["html"]
	assert keepalive == ": keepalive\n\n"


def test_a_new_stream_replaces_the_old_one():

	counter = Counter()
	app = make_app(counter)
	client = app.test_client()
	page_id = load(client)

	old = client.get(f"/_domino/stream?page={page_id}", buffered=False)
	new = client.get(f"/_domino/stream?page={page_id}", buffered=False)

	# The old stream (e.g. a dropped connection the browser replaced) ends
	# instead of taking updates meant for the new one
	assert read_stream(old, 2) == [": open\n\n"]

	counter.refresh()
	assert read_stream(new, 2)[1].startswith("data: ")


def test_stream_ends_when_page_expires():

	app = make_app()
	client = app.test_client()
	page_id = load(client)

	response = client.get(f"/_domino/stream?page={page_id}", buffered=False)
	app.config["DOMINO_PAGE_TTL"] = -1

	assert read_stream(response, 2) == [": open\n\n"]


def test_stream_keeps_its_page_alive():

	app = make_app()
	client = app.test_client()
	page_id = load(client)

	app.config["DOMINO_PAGE_TTL"] = 0.2
	response = client.get(f"/_domino/stream?page={page_id}", buffered=False)

	# Ten keepalives take longer than the TTL; without the stream the page would expire
	chunks = read_stream(response, 11)
	assert chunks[1:] == [": keepalive\n\n"] * 10
	assert page_id in app.page_store.pages


def test_pages_with_nothing_to_update_open_no_stream():

	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document() [
			t.p() [
				"static"
			]
		]

	html = app.test_client().get("/").get_data(as_text=True)

	assert "data-live" not in html
	assert app.page_store.pages == {}


def test_only_live_components_mark_the_page_for_a_stream():

	class Plain(t.div):

		def render(self):
			self(["plain"])

	class Live(t.div):

		live = True

		def render(self):
			self(["live"])

	app = Domino(__name__)

	@app.route("/plain")
	def plain():
		return Document() [Plain()]

	@app.route("/live")
	def live():
		return Document() [Live()]

	client = app.test_client()
	plain_html = client.get("/plain").get_data(as_text=True)
	live_html = client.get("/live").get_data(as_text=True)

	assert "data-live" not in plain_html
	assert len(app.page_store.pages) == 1
	assert "data-live" in live_html
	# `live` itself is not rendered as an HTML attribute
	assert not re.search(r"<div[^>]*\slive[\s=>]", live_html)


def test_refresh_renders_once_for_many_pages_and_shares_events():

	renders = []

	class Shared(t.div):

		live = True

		def render(self):
			renders.append(1)
			self([button := t.button() ["+"]])
			button.bind("click", self.click)

		def click(self):
			return self

	shared = Shared()
	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document() [shared]

	client = app.test_client()
	pages = []
	for _ in range(3):
		html = client.get("/").get_data(as_text=True)
		pages.append(html.split('data-domino-page="')[1].split('"')[0])
	renders.clear()

	shared.refresh()

	assert len(renders) == 1
	event_ids = [set(app.page_store.pages[page_id].events) for page_id in pages]
	assert event_ids[0] == event_ids[1] == event_ids[2] != set()
	for page_id in pages:
		assert app.page_store.pages[page_id].updates[shared.id()]["version"] == 1

