import domino.tags as t
from domino import Domino, State, wait
from domino.components import Document


class Counter(t.div):

	count = State(0)
	items = State([])


	def render(self):

		return [
			t.p() [
				f"Count: {self.count}"
			],
			t.button(on_click=self.increment) [
				"+"
			]
		]


	def increment(self):

		self.count += 1


def render(element):

	return element._render(indent="")


def load(app):

	client = app.test_client()
	html = client.get("/").get_data(as_text=True)
	page_id = html.split('data-domino-page="')[1].split('"')[0]
	event_id = None
	if 'data-event-id="' in html:
		event_id = html.split('data-event-id="')[1].split('"')[0]

	return client, page_id, event_id, html


def test_state_attributes_are_per_instance():

	a, b = Counter(), Counter()
	a.count = 5
	a.items.append("x")

	assert (a.count, b.count) == (5, 0)
	assert b.items == []
	assert isinstance(Counter.count, State)


def test_render_may_return_children():

	class One(t.div):

		def render(self):
			return t.span() ["one"]

	class Text(t.div):

		def render(self):
			return "plain"

	assert "<span>one</span>" in render(One())
	assert "plain" in render(Text())


def test_on_handler_keyword_binds_the_event():

	html = render(t.input(on_input=lambda: None, debounce=250, on_label="not a handler"))

	assert 'data-event-id="' in html and html.split('data-event-id="')[1].startswith("event-")
	assert 'data-debounce-input="250"' in html
	assert 'on-label="not a handler"' in html
	assert "debounce=" not in html


def test_handler_without_return_re_renders_its_component():

	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document() [Counter()]

	client, page_id, event_id, html = load(app)
	assert "Count: 0" in html

	data = client.post("/_domino/events", json={"page_id": page_id, "event_id": event_id}).get_json()
	wait()

	assert "Count: 1" in data["html"]
	# Already in the response, so not pushed to the same page again
	assert app.page_store.pages[page_id].updates == {}


def test_changing_state_from_outside_updates_the_page():

	counter = Counter()
	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document() [counter]

	_, page_id, _, html = load(app)
	assert "data-live" in html

	counter.count = 7

	(update,) = app.page_store.pages[page_id].updates.values()
	assert "Count: 7" in update["html"]


def test_lists_changed_in_place_and_set_again_count_as_changed():

	class Items(t.ul):

		items = State([])

		def render(self):
			return [t.li() [item] for item in self.items]

	items = Items()
	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document() [items]

	_, page_id, _, _ = load(app)

	current = items.items
	current.append("new")
	items.items = current

	(update,) = app.page_store.pages[page_id].updates.values()
	assert "new" in update["html"]


def test_properties_and_state_are_not_rendered_as_attributes():

	class Card(t.div):

		title = "kept as an attribute"
		count = State(1)

		@property
		def label(self):
			return "computed"

	html = render(Card())

	assert 'title="kept as an attribute"' in html
	assert "count=" not in html
	assert "label=" not in html
