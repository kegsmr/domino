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


def make_app():

	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document(title="Counter") [
			Counter()
		]

	@app.route("/plain")
	def plain():
		return "plain"

	return app


def load(client):

	html = client.get("/").get_data(as_text=True)
	page_id = html.split('data-domino-page="')[1].split('"')[0]
	event_id = html.split('data-event-id="')[1].split('"')[0]
	return page_id, event_id


def click(client, page_id, event_id):

	return client.post("/_domino/events", json={"page_id": page_id, "event_id": event_id})


def test_click_updates_component():

	app = make_app()
	client = app.test_client()
	page_id, event_id = load(client)

	response = click(client, page_id, event_id)

	assert response.status_code == 200
	assert "Count: 1" in response.get_json()["html"]


def test_events_do_not_accumulate_on_rerender():

	app = make_app()
	client = app.test_client()
	page_id, event_id = load(client)

	for _ in range(50):
		data = click(client, page_id, event_id).get_json()
		event_id = data["html"].split('data-event-id="')[1].split('"')[0]

	assert "Count: 50" in data["html"]
	assert len(app.page_store.pages[page_id].events) == 1


def test_pages_are_isolated():

	app = make_app()
	client = app.test_client()
	page_a, event_a = load(client)
	page_b, event_b = load(client)

	click(client, page_a, event_a)
	html_b = click(client, page_b, event_b).get_json()["html"]

	assert "Count: 1" in html_b


def test_unknown_event_is_404():

	app = make_app()
	client = app.test_client()
	page_id, _ = load(client)

	assert click(client, page_id, "nope").status_code == 404
	assert client.post("/_domino/events", json={}).status_code == 404


def test_pages_expire_and_are_capped():

	app = make_app()
	app.config["DOMINO_MAX_PAGES"] = 3
	client = app.test_client()

	for _ in range(10):
		load(client)
	assert len(app.page_store.pages) == 3

	app.config["DOMINO_PAGE_TTL"] = -1
	page_id, event_id = load(client)
	assert click(client, page_id, event_id).status_code == 404


def test_routes_without_events_keep_no_page():

	app = make_app()
	client = app.test_client()

	assert client.get("/plain").get_data(as_text=True) == "plain"
	assert app.page_store.pages == {}


def test_handle_event_returns_the_payload_and_status_for_any_transport():

	app = make_app()
	client = app.test_client()
	page_id, event_id = load(client)
	page = app.page_store.pages[page_id]

	with app.test_request_context():
		payload, status = app.handle_event(page, event_id, {})
		missing = app.handle_event(page, "nope", None)

	assert status == 200
	assert set(payload) == {"id", "html", "version"}
	assert "Count: 1" in payload["html"]
	assert missing == ({"error": "Unknown or expired event"}, 404)
