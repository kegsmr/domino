import json

import domino.tags as t
from domino import Collection, Domino, State
from domino import _optimistic as optimistic
from domino import Document
from domino._optimistic import predictable_methods


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


class Stepper(t.div):

	value = State(0)
	top = 5


	def render(self):

		return [
			t.button(on_click=self.decrement) ["-"],
			t.output() [str(self.value)],
			t.button(on_click=self.increment) ["+"],
		]


	def increment(self):

		self.value = min(5, self.value + 1)


	def decrement(self):

		self.value = max(0, self.value - 1)


class Menu(t.div):
	"""Its options, and their buttons, exist only while it's open."""

	open = State(False)
	choice = State("a")


	def render(self):

		children = [t.button(class_="toggle", on_click=self.toggle) [f"Sort: {self.choice}"]]
		if self.open:
			children += [
				t.button(class_="option", on_click=lambda event, option=option: self.pick(option)) [option]
				for option in "abc"
			]
		children.append(t.button(class_="save", on_click=self.save) ["save"])

		return children


	def toggle(self):

		self.open = not self.open


	def pick(self, option):

		self.choice = option
		self.open = False


	def save(self):

		notes.insert({"choice": self.choice})


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


def html_of(graph, index):
	"""A state's HTML, following a reference to a state with the same HTML."""

	html = graph["states"][index]
	return graph["states"][html] if isinstance(html, int) else html


def event_ids(component, html):
	"""The component's event ids in `html`, without the "event-<id>-" they start with."""

	prefix = f"event-{component.id()}-"
	found = []
	for part in html.split('data-event-id="')[1:]:
		found += [event_id[len(prefix):] for event_id in part.split('"')[0].split() if event_id.startswith(prefix)]

	return found


def test_only_handlers_that_just_change_own_state_are_predictable():

	assert predictable_methods(Widget) == {"increment", "toggle", "add_item"}


def test_predictions_show_the_state_after_each_handler_without_changing_it():

	widget = Widget()
	_, _, html, _ = serve(widget)
	graph = predictions_in(html)

	assert widget.count == 0 and widget.open is False and widget.items == []
	# count can grow forever, so just one step ahead: edges from the current state alone
	assert len(graph["edges"]) == 1
	assert len(graph["edges"][0]) == 3
	# The current state (0) is in the page already
	assert graph["states"][0] is None
	assert any("Count: 1" in html_of(graph, index) for index in graph["edges"][0].values())
	# Predictions are complete renders of the component, without predictions of their own
	assert all("data-domino-predict" not in html_of(graph, index) for index in range(1, len(graph["states"])))


def test_handlers_with_side_effects_are_never_run_ahead():

	before = notes.count()
	serve(Widget())
	serve(Menu())

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
	graph = predictions_in(data["html"])
	assert any("Count: 2" in html_of(graph, index) for index in graph["edges"][0].values())
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
	assert "<!--" not in script.split("</script>")[0]


def test_a_bounded_component_ships_every_state_it_can_reach():

	stepper = Stepper()
	_, _, html, _ = serve(stepper)
	graph = predictions_in(html)

	# 0 to 5, each rendered once, each with where - and + lead
	assert len(graph["states"]) == 6
	assert len(graph["edges"]) == 6
	shown = {index: html_of(graph, index) for index in range(1, 6)}
	assert sorted(html.split("<output>")[1].split("</output>")[0].strip() for html in shown.values()) == ["1", "2", "3", "4", "5"]

	minus, plus = event_ids(stepper, html)
	# Following + five times from 0 reaches 5 and stays there; - goes back
	state = 0
	for _ in range(7):
		state = graph["edges"][state][plus]
	assert "5" in html_of(graph, state)
	assert graph["edges"][state][plus] == state
	assert graph["edges"][graph["edges"][state][minus]][plus] == state
	# The state it is in is real and unchanged
	assert stepper.value == 0


def test_identical_html_is_sent_once():

	class Hidden(t.div):

		shown = State(False)
		secret = State(0)

		def render(self):
			return [t.p() ["on" if self.shown else "off"], t.button(on_click=self.flip) ["flip"], t.button(on_click=self.bump) ["bump"]]

		def flip(self):
			self.shown = not self.shown

		def bump(self):
			self.secret = (self.secret + 1) % 3

	_, _, html, _ = serve(Hidden())
	graph = predictions_in(html)

	# 2 x 3 states, but only two different HTMLs, one of them the current one (not sent)
	assert len(graph["states"]) == 6
	strings = [state for state in graph["states"] if isinstance(state, str)]
	assert len(strings) == 2 and len(set(strings)) == 2
	assert sum(isinstance(state, int) for state in graph["states"]) == 3


def test_too_many_states_fall_back_to_one_step():

	class Wide(Stepper):

		def increment(self):
			self.value = min(50, self.value + 1)

	stepper = Wide()
	_, _, html, _ = serve(stepper)
	graph = predictions_in(html)

	assert len(graph["edges"]) == 1
	# - stays at 0 (the current state), + goes to 1
	assert sorted(graph["edges"][0].values()) == [0, 1]
	assert len(graph["states"]) == 2


def test_optimistic_states_sets_the_limit_and_is_not_an_attribute():

	class Small(Stepper):

		optimistic_states = 3

	_, _, html, _ = serve(Small())
	graph = predictions_in(html)

	assert len(graph["edges"]) == 1
	assert "optimistic" not in html.split("data-domino-predict")[0]


def test_html_over_the_budget_falls_back_to_one_step(monkeypatch):

	monkeypatch.setattr(optimistic, "MAX_BYTES", 300)
	_, _, html, _ = serve(Stepper())
	graph = predictions_in(html)

	assert len(graph["edges"]) == 1


def test_an_unbounded_counter_renders_only_the_next_step():

	renders = []

	class Counter(t.div):

		count = State(0)

		def render(self):
			renders.append(self.count)
			return [t.p() [str(self.count)], t.button(on_click=self.up) ["+"], t.button(on_click=self.down) ["-"]]

		def up(self):
			self.count += 1

		def down(self):
			self.count -= 1

	_, _, html, _ = serve(Counter())
	graph = predictions_in(html)

	assert len(graph["edges"]) == 1 and len(graph["states"]) == 3
	# The real render and one per state one step away, as before the graph
	assert sorted(renders) == [-1, 0, 1]


def test_edges_follow_buttons_that_only_some_states_have():

	menu = Menu()
	_, _, html, _ = serve(menu)
	graph = predictions_in(html)

	# Closed or open, times three choices
	assert len(graph["states"]) == 6 and len(graph["edges"]) == 6

	real = html.split("data-domino-predict")[0]
	for index, edges in enumerate(graph["edges"]):
		ids = event_ids(menu, real if index == 0 else html_of(graph, index))
		# Each state's edges use the event ids that state's own HTML has
		assert set(edges) <= set(ids)
		# Every button but save (which writes to the database) leads somewhere
		assert len(edges) == len(ids) - 1

	# Open the menu, then pick "c": closed again, showing c
	toggle = event_ids(menu, real)[0]
	opened = graph["edges"][0][toggle]
	pick_c = event_ids(menu, html_of(graph, opened))[3]
	picked = html_of(graph, graph["edges"][opened][pick_c])
	assert "Sort: c" in picked and "option" not in picked


def test_lambdas_that_only_call_a_predictable_method_are_predicted():

	class Picker(t.div):

		chosen = State(0)

		def render(self):
			return [
				t.button(on_click=lambda event, number=number: self.choose(number)) [str(number)]
				for number in range(3)
			] + [
				t.button(on_click=lambda event: self.choose(event.value)) ["from the event"],
				t.button(on_click=lambda: self.log(1)) ["calls a method that isn't predictable"],
				t.button(on_click=lambda: print(1)) ["calls a function"],
				t.p() [f"Chosen: {self.chosen}"],
			]

		def choose(self, number):
			self.chosen = number

		def log(self, number):
			notes.insert({"number": number})

	picker = Picker()
	_, _, html, _ = serve(picker)
	graph = predictions_in(html)

	assert len(graph["states"]) == 3
	assert all(len(edges) == 3 for edges in graph["edges"])
	assert sorted(html_of(graph, index).split("Chosen: ")[1][0] for index in (1, 2)) == ["1", "2"]


def test_a_line_with_an_unsafe_lambda_is_not_predicted():

	class Shared(t.div):

		value = State(0)

		def render(self):
			# Both lambdas start on this line: which one is which can't be told, so neither counts
			a, b = (lambda event: self.set(1)), (lambda event: notes.insert({}))
			return [t.button(on_click=a) ["a"], t.p() [str(self.value)]]

		def set(self, value):
			self.value = value

	_, _, html, _ = serve(Shared())

	assert "data-domino-predict" not in html


def test_predicting_cannot_change_lists_in_place():

	class Bag(t.div):

		items = State([])

		def render(self):
			return [t.button(on_click=self.add) ["add"], t.p() [str(len(self.items))]]

		def add(self):
			if len(self.items) < 2:
				self.items += ["x"]

	bag = Bag()
	_, _, html, _ = serve(bag)

	assert bag.items == []
	assert len(predictions_in(html)["states"]) == 3


def test_predicting_keeps_subscriptions_and_children():

	class Child(t.div):

		on = State(False)

		def render(self):
			return [t.button(on_click=self.flip) ["on" if self.on else "off"]]

		def flip(self):
			self.on = not self.on

	child = Child()

	class Parent(t.div):

		tab = State(0)

		def render(self):
			return [t.button(on_click=self.next) [str(self.tab)], child]

		def next(self):
			self.tab = (self.tab + 1) % 2

	parent = Parent()
	_, _, html, _ = serve(parent)

	tab = type(parent).tab._of(parent)._dependency
	on = type(child).on._of(child)._dependency
	assert set(tab.dependents) == {parent}
	assert set(on.dependents) == {child}
	assert parent.__children__[1] is child
	# Each ships its own states
	assert html.count("data-domino-predict") == 2
