import domino.tags as t
from domino import Domino
from domino.components import Document


def render(element):

	return element._render(indent="")


def test_several_events_on_one_element():

	box = t.input()
	box.bind("input", lambda: None)
	box.bind("change", lambda: None)

	event_ids = render(box).split('data-event-id="')[1].split('"')[0].split()

	assert [event_id.rsplit("-", 1)[1] for event_id in event_ids] == ["input", "change"]


def test_rebinding_the_same_event_does_not_duplicate():

	class Box(t.div):

		def render(self):
			self.bind("click", self.click)

		def click(self):
			return self

	box = Box()
	render(box)
	html = render(box)

	assert len(html.split('data-event-id="')[1].split('"')[0].split()) == 1


def test_debounce_attribute():

	box = t.input()
	box.bind("input", lambda: None, debounce=250)

	assert 'data-debounce-input="250"' in render(box)


def test_event_responses_carry_increasing_versions():

	class Counter(t.div):

		def render(self):
			self([button := t.button() ["+"]])
			button.bind("click", self.click)

		def click(self):
			return self

	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document() [Counter()]

	client = app.test_client()
	html = client.get("/").get_data(as_text=True)
	page_id = html.split('data-domino-page="')[1].split('"')[0]
	event_id = html.split('data-event-id="')[1].split('"')[0]

	versions = [
		client.post("/_domino/events", json={"page_id": page_id, "event_id": event_id}).get_json()["version"]
		for _ in range(3)
	]

	assert versions == [1, 2, 3]
