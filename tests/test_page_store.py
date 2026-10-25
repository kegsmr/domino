import threading
import time

import domino.tags as t
from domino import Domino, MemoryPageStore
from domino.components import Document


class SlowCounter(t.div):


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

		# Read-modify-write with a gap, so unserialized events would lose updates
		count = self.count
		time.sleep(0.001)
		self.count = count + 1

		return self


class RecordingStore(MemoryPageStore):


	def __init__(self):

		super().__init__()

		self.saved = 0


	def save(self, page):

		self.saved += 1
		super().save(page)


def make_app(**kwargs):

	app = Domino(__name__, **kwargs)
	counter = SlowCounter()

	@app.route("/")
	def index():
		return Document() [
			counter
		]

	return app, counter


def test_custom_page_store_is_used():

	store = RecordingStore()
	app, _ = make_app(page_store=store)

	app.test_client().get("/")

	assert app.page_store is store
	assert store.saved == 1
	assert len(store.pages) == 1


def test_concurrent_events_on_one_page_are_serialized():

	app, counter = make_app()
	client = app.test_client()
	html = client.get("/").get_data(as_text=True)
	page_id = html.split('data-domino-page="')[1].split('"')[0]
	event_id = html.split('data-event-id="')[1].split('"')[0]

	def click():
		app.test_client().post("/_domino/events", json={"page_id": page_id, "event_id": event_id})

	threads = [threading.Thread(target=click) for _ in range(50)]
	for thread in threads:
		thread.start()
	for thread in threads:
		thread.join()

	assert counter.count == 50


def test_event_ids_are_stable_across_rerenders():

	app, _ = make_app()
	client = app.test_client()
	html = client.get("/").get_data(as_text=True)
	page_id = html.split('data-domino-page="')[1].split('"')[0]
	event_id = html.split('data-event-id="')[1].split('"')[0]

	for expected in range(1, 4):
		response = client.post("/_domino/events", json={"page_id": page_id, "event_id": event_id})
		assert response.status_code == 200
		assert f"Count: {expected}" in response.get_json()["html"]
		assert f'data-event-id="{event_id}"' in response.get_json()["html"]
