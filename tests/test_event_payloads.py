import domino.tags as t
from domino import Domino, Event
from domino import Document


class Greeter(t.div):


	def __init__(self, *args, **kwargs):

		super().__init__(*args, **kwargs)

		self.received = None
		self.clicks = 0


	def render(self):

		self([
			form := t.form() [
				t.input(name="name")
			],
			button := t.button() [
				"plain"
			]
		])

		form.bind("submit", self.submit)
		button.bind("click", self.click)


	def submit(self, event):

		self.received = event

		return self


	def click(self):

		self.clicks += 1

		return self


def setup():

	app = Domino(__name__)
	greeter = Greeter()

	@app.route("/")
	def index():
		return Document() [
			greeter
		]

	client = app.test_client()
	html = client.get("/").get_data(as_text=True)
	page_id = html.split('data-domino-page="')[1].split('"')[0]
	event_ids = [part.split('"')[0] for part in html.split('data-event-id="')[1:]]
	return client, greeter, page_id, event_ids


def test_callback_receives_event_with_form_and_value():

	client, greeter, page_id, event_ids = setup()
	submit_id = next(event_id for event_id in event_ids if event_id.endswith("-submit"))

	response = client.post("/_domino/events", json={
		"page_id": page_id,
		"event_id": submit_id,
		"data": {"value": "x", "form": {"name": "Ada", "tags": ["a", "b"]}}
	})

	assert response.status_code == 200
	assert isinstance(greeter.received, Event)
	assert greeter.received.type == "submit"
	assert greeter.received.value == "x"
	assert greeter.received.form == {"name": "Ada", "tags": ["a", "b"]}


def test_missing_or_malformed_data_gives_empty_event():

	client, greeter, page_id, event_ids = setup()
	submit_id = next(event_id for event_id in event_ids if event_id.endswith("-submit"))

	client.post("/_domino/events", json={"page_id": page_id, "event_id": submit_id, "data": "junk"})

	assert greeter.received.value is None
	assert greeter.received.form == {}


def test_callbacks_without_arguments_still_work():

	client, greeter, page_id, event_ids = setup()
	click_id = next(event_id for event_id in event_ids if event_id.endswith("-click"))

	response = client.post("/_domino/events", json={"page_id": page_id, "event_id": click_id})

	assert response.status_code == 200
	assert greeter.clicks == 1


def test_after_events_have_after_type():

	assert Event.from_request("after-abc-def-100", None).type == "after"
	assert Event.from_request("event-abc-def-change", None).type == "change"
