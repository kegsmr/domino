import logging

import domino.tags as t
from domino import Domino
from domino.components import Document


class Flaky(t.div):
	"""Raises from its callback or its render() on demand."""


	def __init__(self, *args, **kwargs):

		super().__init__(*args, **kwargs)

		self.count = 0
		self.fail_callback = False
		self.fail_render = False


	def render(self):

		if self.fail_render:
			raise RuntimeError("render broke")

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

		if self.fail_callback:
			raise ValueError("secret detail")

		self.count += 1

		return self


def make_app(component, debug=False):

	app = Domino(__name__)
	app.debug = debug

	@app.route("/")
	def index():
		return Document() [
			component
		]

	return app


def load(client):

	html = client.get("/").get_data(as_text=True)
	page_id = html.split('data-domino-page="')[1].split('"')[0]
	event_id = html.split('data-event-id="')[1].split('"')[0]
	return page_id, event_id


def click(client, page_id, event_id):

	return client.post("/_domino/events", json={"page_id": page_id, "event_id": event_id})


def test_production_error_hides_details(caplog):

	flaky = Flaky()
	flaky.fail_callback = True
	client = make_app(flaky).test_client()

	with caplog.at_level(logging.ERROR):
		response = click(client, *load(client))

	assert response.status_code == 500
	data = response.get_json()
	assert set(data) == {"error"}
	assert "secret detail" not in response.get_data(as_text=True)
	assert "Traceback" not in response.get_data(as_text=True)
	assert "secret detail" in caplog.text
	assert any(record.exc_info for record in caplog.records)


def test_debug_error_includes_traceback(caplog):

	flaky = Flaky()
	flaky.fail_callback = True
	client = make_app(flaky, debug=True).test_client()

	with caplog.at_level(logging.ERROR):
		response = click(client, *load(client))

	assert response.status_code == 500
	data = response.get_json()
	assert data["error"] == "ValueError: secret detail"
	assert data["debug"] is True
	assert "Traceback" in data["traceback"]
	assert "in increment" in data["traceback"]
	assert "version" not in data
	assert any(record.exc_info for record in caplog.records)


def test_failed_callback_keeps_the_button_working():

	flaky = Flaky()
	flaky.fail_callback = True
	client = make_app(flaky).test_client()
	page_id, event_id = load(client)

	assert click(client, page_id, event_id).status_code == 500

	flaky.fail_callback = False
	response = click(client, page_id, event_id)

	assert response.status_code == 200
	assert "Count: 1" in response.get_json()["html"]


def test_failed_render_keeps_the_old_events():

	flaky = Flaky()
	app = make_app(flaky)
	client = app.test_client()
	page_id, event_id = load(client)
	events = dict(app.page_store.pages[page_id].events)

	# The callback runs (count becomes 1) but the re-render fails, so the browser
	# keeps the old button; its event must still be there
	flaky.fail_render = True
	assert click(client, page_id, event_id).status_code == 500
	assert app.page_store.pages[page_id].events == events

	flaky.fail_render = False
	response = click(client, page_id, event_id)

	assert response.status_code == 200
	assert "Count: 2" in response.get_json()["html"]


def test_failed_render_drops_events_it_bound():

	class Partial(Flaky):


		def render(self):

			# Bind a new event, then fail before the render finishes
			t.button().bind("click", self.increment)
			super().render()


	partial = Partial()
	app = make_app(partial)
	client = app.test_client()
	page_id, event_id = load(client)
	events = dict(app.page_store.pages[page_id].events)

	partial.fail_render = True
	assert click(client, page_id, event_id).status_code == 500
	assert app.page_store.pages[page_id].events == events


def test_failed_event_does_not_bump_the_version():

	flaky = Flaky()
	app = make_app(flaky)
	client = app.test_client()
	page_id, event_id = load(client)

	flaky.fail_callback = True
	click(client, page_id, event_id)

	assert app.page_store.pages[page_id].version == 0
