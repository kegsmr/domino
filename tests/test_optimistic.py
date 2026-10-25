import json

import domino.tags as t
from domino import Collection, Domino, State
from domino.components import Document
from domino.optimistic import predictable_methods


notes = Collection()


class Widget(t.div):

	count = State(0)
	open = State(False)
	items = State([])
	label = "plain attribute"


	def render(self):

		return [
			t.p() [f"Count: {self.count}"],
			t.button(on_click=self.increment) ["+"],
			t.button(on_click=self.toggle) ["toggle"],
			t.button(on_click=self.add_item) ["add"],
			t.button(on_click=self.save) ["save"],
		]


	def increment(self):

		self.count += 1


	def toggle(self, event):

		"""Flip the panel."""
		self.open = not self.open


	def add_item(self):

		if len(self.items) < 3:
			self.items = self.items + [f"item {self.count}"]
		else:
			self.items = []


	def save(self):

		notes.insert({"count": self.count})


	def uses_event(self, event):

		self.count = event.value


	def uses_local(self):

		step = 2
		self.count += step


	def plain_attribute(self):

		self.label = "changed"


	def calls_method(self):

		self.count = self.compute()


def predictions_in(html):

	script = html.split("data-domino-predict>")[1].split("</script>")[0]
	return json.loads(script)


def serve(component):

	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document() [component]

	client = app.test_client()
	html = client.get("/").get_data(as_text=True)
	page_id = html.split('data-domino-page="')[1].split('"')[0]

	return app, client, html, page_id


def test_only_handlers_that_just_change_own_state_are_predictable():

	assert predictable_methods(Widget) == {"increment", "toggle", "add_item"}


def test_predictions_show_the_state_after_each_handler_without_changing_it():

	widget = Widget()
	_, _, html, _ = serve(widget)
	predictions = predictions_in(html)

	assert widget.count == 0 and widget.open is False and widget.items == []
	assert len(predictions) == 3
	assert any("Count: 1" in prediction for prediction in predictions.values())
	# Predictions are complete renders of the component, without predictions of their own
	assert all("data-domino-predict" not in prediction for prediction in predictions.values())


def test_handlers_with_side_effects_are_never_run_ahead():

	before = notes.count()
	serve(Widget())

	assert notes.count() == before


def test_events_still_work_after_predicting():

	widget = Widget()
	app, client, html, page_id = serve(widget)
	page = app.page_store.pages[page_id]
	increment_id = next(event_id for event_id, (_, callback) in page.events.items() if callback.__name__ == "increment")

	data = client.post("/_domino/events", json={"page_id": page_id, "event_id": increment_id}).get_json()

	assert widget.count == 1
	assert "Count: 1" in data["html"]
	# The response predicts the next click from the new state
	assert any("Count: 2" in prediction for prediction in predictions_in(data["html"]).values())
	# Each event is registered once, for the real elements
	assert len(page.events) == len(set(page.events))
	assert all(event in page.subtree_events(widget) for event in page.events)


def test_optimistic_false_turns_it_off_and_is_not_an_attribute():

	class Quiet(Widget):

		optimistic = False

	_, _, html, _ = serve(Quiet())

	assert "data-domino-predict" not in html
	assert "optimistic" not in html


def test_predictions_cannot_break_out_of_their_script():

	class Tricky(t.div):

		text = State("</script><script>alert(1)</script>")

		def render(self):
			return [t.p() [self.text], t.button(on_click=self.clear) ["x"]]

		def clear(self):
			self.text = ""

	_, _, html, _ = serve(Tricky())
	script = html.split("data-domino-predict>")[1]

	assert "</script><script>" not in script.split("</script>")[0]
