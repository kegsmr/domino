import functools
import html
import importlib.util
import json
import re
import textwrap
import time
import uuid
from copy import deepcopy

import pytest
from markupsafe import escape

import domino.tags as t
from domino import Collection, Domino, State, optimistic, patches, reactive
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
	"""A state's HTML, following a reference to a state with the same HTML, or applying a patch
	against the base state."""

	html = graph["states"][index]
	if isinstance(html, int):
		return html_of(graph, html)
	if isinstance(html, list):
		return patches.apply(graph["states"][graph["base"]], html)
	return html


def event_ids(component, html):
	"""The component's event ids in `html`, without the "event-<id>-" they start with."""

	prefix = f"event-{component.id()}-"
	found = []
	for part in html.split('data-event-id="')[1:]:
		found += [event_id[len(prefix):] for event_id in part.split('"')[0].split() if event_id.startswith(prefix)]

	return found


def test_only_handlers_that_just_change_own_state_are_predictable():

	# save() writes to a collection, which a prediction keeps aside; uses_event() reads
	# event.value, predicted only for elements with a few values
	assert predictable_methods(Widget) == {"increment", "toggle", "add_item", "uses_local", "uses_event", "save"}


def test_predictions_show_the_state_after_each_handler_without_changing_it():

	widget = Widget()
	_, _, html, _ = serve(widget)
	graph = predictions_in(html)

	assert widget.count == 0 and widget.open is False and widget.items == []
	# count can grow forever, so just one step ahead: edges from the current state alone
	assert len(graph["edges"]) == 1
	# save() included: its write to the collection is kept aside (the Widget doesn't show it)
	assert len(graph["edges"][0]) == 4
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

	# Closed or open, times three choices, and where save leads from the current state (it writes
	# to a collection, which makes a new state every time, so it's followed one step only)
	assert len(graph["states"]) == 7 and len(graph["edges"]) == 6

	real = html.split("data-domino-predict")[0]
	for index, edges in enumerate(graph["edges"]):
		ids = event_ids(menu, real if index == 0 else html_of(graph, index))
		# Each state's edges use the event ids that state's own HTML has
		assert set(edges) <= set(ids)
		# Every button leads somewhere, save only from the current state
		assert len(edges) == len(ids) - (index > 0)

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
				t.input(on_input=lambda event: self.choose(event.value)),
				t.button(on_click=lambda: self.log(1)) ["calls a method that isn't predictable"],
				t.button(on_click=lambda: print(1)) ["calls a function"],
				t.p() [f"Chosen: {self.chosen}"],
			]

		def choose(self, number):
			self.chosen = number

		def log(self, number):
			print(number)

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
			# Both lambdas start on this line and call set(): which one is which can't be told
			# for sure, so neither counts
			a, b = (lambda event: self.set(1)), (lambda event: self.set(notes.insert({})))
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


# What qualifies: each construct a handler may use, and those it may not


def graph_of(component):

	return predictions_in(serve(component)[2])


def html_text(graph, index):
	"""A state's text, without its tags, unescaped."""

	return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", html_of(graph, index))).split())


SAMPLE = '''
import time

import domino.tags as t
from domino import Collection, State

notes = Collection()
LIMIT = 3
LIMITS = [1, 2]


class Sample(t.div):

	count = State(0)
	items = State([3, 1, 2])
	flags = State({"a": True})
	text = State(" Hello, World ")
	label = "plain attribute"

	def render(self):
		return [t.p() [str(self.count)], t.button(on_click=self.handler) ["go"]]

	def helper(self, value):
		self.count = value

	def handler(self, event):
{body}
'''


def sample_class(tmp_path, body, name):
	"""The Sample class above with handler() of `body`, from a module of its own (its source
	must be in a file for the checks to read)."""

	path = tmp_path / f"{name}.py"
	path.write_text(SAMPLE.replace("{body}", textwrap.indent(textwrap.dedent(body).strip(), "\t\t")))
	spec = importlib.util.spec_from_file_location(name, path)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)

	return module.Sample


ALLOWED = {
	"local variables": "step = 2\nself.count += step",
	"tuple unpacking": "a, (b, c) = self.count, (1, 2)\nself.count, first, *rest = a + b + c, 1, 2, 3",
	"dict and set literals": "self.flags = {'a': not self.flags['a'], 'b': {1, 2} == {2, 1}}",
	"comprehensions": "self.items = [n * 2 for n in self.items if n > 1]\nself.flags = {str(k): v for k, v in enumerate(self.items)}\nself.count = sum(n for n in self.items)\nself.items = sorted({n % 2 for n in range(4)})",
	"range, enumerate, zip, reversed, any, all": "pairs = list(zip(range(3), reversed(self.items)))\nself.count = len([i for i, _ in enumerate(pairs)]) + any(self.items) + all(self.items)",
	"pure str methods": "words = [w.strip().lower() for w in self.text.split(',')]\nself.text = '-'.join(words).replace('o', '0').upper() if words[0].startswith('h') else ''",
	"dict.get and list.index and count": "self.count = self.flags.get('b', 0) + self.items.index(1) + self.items.count(3)",
	"slicing": "self.items = self.items[1:] + self.items[:1]\nself.text = self.text[::-1]",
	"in-place changes of State": "self.items.append(4)\nself.items.remove(3)\nself.items.insert(0, 9)\nself.items.extend([5])\nself.items.pop()\nself.items.sort()\nself.flags['b'] = 1\ndel self.items[0]\nself.items += [7]\nself.flags.update({'c': 2})\nself.flags.pop('a')",
	"for loops, break and continue": "for n in self.items:\n    if n == 1:\n        continue\n    if n > 2:\n        break\n    self.count += n",
	"early return": "if self.count > 2:\n    return\nself.count += 1",
	"calls of other predictable methods": "self.helper(self.count + 1)",
	"event.form fields": "self.text = event.form['text'].strip()[:10]",
	"event.value": "self.count = event.value",
	"collections": "self.count = notes.count({'done': False})\nnotes.insert({'text': self.text, 'at': time.time()})\nnotes.update({'_id': 'x'}, {'$set': {'done': True}})\nnotes.remove({'done': True})",
}


@pytest.mark.parametrize("construct", sorted(ALLOWED))
def test_each_construct_a_handler_may_use(construct, tmp_path):

	cls = sample_class(tmp_path, ALLOWED[construct], f"allowed_{abs(hash(construct))}")

	assert "handler" in predictable_methods(cls), optimistic.explain(cls(), cls().handler)


REJECTED = {
	"a function": ("print(self.count)", "calls print()"),
	"a global": ("self.count = LIMIT", "reads LIMIT"),
	"a method of a global": ("LIMITS.append(1)", "reads LIMITS"),
	"an attribute that isn't State": ("self.count = self.label", "attribute of something other than the component's State"),
	"the event itself": ("self.count = event", "reads the event"),
	"another attribute of the event": ("self.count = event.type", "attribute of something other"),
	"event.form other than by name": ("self.text = event.form[self.text]", "event.form other than by a field's name"),
	"a method of the component that isn't predictable": ("self.refresh()", "isn't a predictable method"),
	"a while loop": ("while self.count < 3:\n    self.count += 1", "while loops"),
	"try": ("try:\n    self.count = 1\nexcept Exception:\n    pass", "not with, try"),
	"with": ("with self.items:\n    pass", "not with, try"),
	"an import": ("import os", "imports"),
	"a nested function": ("def inner():\n    pass", "defines a function"),
	"a lambda": ("self.count = (lambda: 1)()", "calls something other than a function by its name"),
	"str.format": ("self.text = '{}'.format(self.count)", "isn't a method of plain values"),
	"a dunder method": ("self.items.__setitem__(0, 1)", "isn't a method of plain values"),
	"a walrus": ("self.count = (n := 1)", "NamedExpr"),
	"getattr": ("self.count = getattr(self, 'count')", "calls getattr()"),
	"a builtin by another name": ("f = len\nself.count = f(self.items)", "reads len"),
	"a call through a local": ("f = self.items\nself.count = f()", "calls f()"),
	"** arguments": ("self.count = max(**self.flags)", "**"),
	"another method of a collection": ("notes.store()", "calls notes.store()"),
	"a module's other functions": ("time.sleep(1)", "calls time.sleep()"),
	"assigning to self": ("self = None", "assigns to self"),
	"returning a value": ("return self.count", "returns a value"),
	"raise": ("raise ValueError()", "raise"),
	"global": ("global LIMIT", "globals"),
	"open()": ("open('x', 'w')", "calls open()"),
	"eval()": ("eval('1')", "calls eval()"),
	"type()": ("self.count = type(self.items)", "calls type()"),
}


@pytest.mark.parametrize("construct", sorted(REJECTED))
def test_each_construct_a_handler_may_not_use(construct, tmp_path):

	body, reason = REJECTED[construct]
	cls = sample_class(tmp_path, body, f"rejected_{abs(hash(construct))}")
	component = cls()

	assert "handler" not in predictable_methods(cls)
	explained = optimistic.explain(component, component.handler)
	assert reason in explained and "line" in explained


def test_local_variables_unpacking_and_methods_predict_right():

	class Swapper(t.div):

		a = State(1)
		b = State(2)
		text = State(" Apple, banana,,Cherry ")

		def render(self):
			return [t.p() [f"{self.a} {self.b} {self.text}"], t.button(on_click=self.swap) ["swap"]]

		def swap(self):
			step = 10
			first, second = self.a, self.b
			self.a, self.b = second + step, first
			words = [word.strip().lower() for word in self.text.split(",") if word.strip()]
			self.text = "/".join(sorted(set(words), reverse=True)[:2])

	graph = graph_of(Swapper())

	assert html_text(graph, graph["edges"][0]["1-click"]) == "12 1 cherry/banana swap"


def test_changes_in_place_are_predicted_on_copies():

	class Board(t.div):

		items = State(["b", "a"])
		flags = State({"x": False})
		tags = State({"t"})

		def render(self):
			return [t.p() [f"{self.items} {sorted(self.flags.items())} {sorted(self.tags)}"], t.button(on_click=self.shuffle) ["go"]]

		def shuffle(self):
			self.items.append("c")
			self.items.insert(0, "z")
			self.items.extend(["d", "e"])
			self.items.remove("b")
			self.items.pop()
			del self.items[0]
			self.items += ["f"]
			self.items.sort()
			self.flags["x"] = not self.flags["x"]
			self.flags.update({"y": len(self.items)})
			self.tags.add("u")
			self.tags.discard("t")

	board = Board()
	graph = graph_of(board)

	assert html_text(graph, graph["edges"][0]["1-click"]) == "['a', 'c', 'd', 'f'] [('x', True), ('y', 4)] ['u'] go"
	# The real values are as they were
	assert board.items == ["b", "a"] and board.flags == {"x": False} and board.tags == {"t"}


def test_loops_and_early_return_predict_right():

	class Totals(t.div):

		values = State([3, -1, 4, -1, 5])
		total = State(0)

		def render(self):
			return [t.p() [str(self.total)], t.button(on_click=self.add_up) ["sum"]]

		def add_up(self):
			if self.total:
				self.total = 0
				return
			for value in self.values:
				if value < 0:
					continue
				if value > 4:
					break
				self.total += value

	graph = graph_of(Totals())

	# 0 -> 7 -> 0: both states, the whole graph
	assert len(graph["states"]) == 2
	assert html_text(graph, 1) == "7 sum"
	assert graph["edges"][1]["1-click"] == 0


def test_handlers_call_other_predictable_methods():

	class Selector(t.div):

		selected = State(None)
		history = State([])

		def render(self):
			return [
				t.p() [f"{self.selected} {self.history}"],
				*[t.button(on_click=lambda event, number=number: self.select(number)) [str(number)] for number in range(2)],
				t.button(on_click=self.clear) ["clear"],
				t.button(on_click=self.forever) ["forever"],
			]

		def select(self, number):
			self.remember(number)
			self.selected = number

		def remember(self, number):
			self.history = (self.history + [number])[-2:]

		def clear(self):
			self.select(None)

		def forever(self):
			self.forever()

	assert optimistic.callable_methods(Selector) == {"select": 1, "remember": 1, "clear": 0, "forever": 0}
	graph = graph_of(Selector())
	edges = graph["edges"][0]

	assert html_text(graph, edges["1-click"]).startswith("0 [0]")
	assert html_text(graph, edges["2-click"]).startswith("1 [1]")
	assert html_text(graph, edges["3-click"]).startswith("None [None]")
	# Recursing forever stops the prediction, not the render
	assert "4-click" not in edges


def test_functools_partial_of_a_predictable_method_is_predicted():

	class Picker(t.div):

		chosen = State(0)

		def render(self):
			return [t.button(on_click=functools.partial(self.choose, number)) [str(number)] for number in range(3)] + [t.p() [str(self.chosen)]]

		def choose(self, number):
			self.chosen = number

	graph = graph_of(Picker())

	assert len(graph["states"]) == 3 and all(len(edges) == 3 for edges in graph["edges"])


def test_predictions_run_a_sandboxed_copy_of_the_method():

	compiled = optimistic.compiled(Widget, "save")

	# Only safe builtins, the helpers that check calls, and the module's Collections and modules
	allowed = set(optimistic.SANDBOX) | set(optimistic.module_names(globals())) | {"save"}
	assert set(compiled.__globals__) <= allowed
	assert compiled.__globals__["__builtins__"] == {}
	assert compiled is not Widget.save

	# Method calls are checked by the value's exact type when they run
	assert optimistic.call_method([1], "count", 1) == 1
	with pytest.raises(optimistic.Unpredictable):
		optimistic.call_method(object(), "count", 1)
	with pytest.raises(optimistic.Unpredictable):
		optimistic.call_method(time, "sleep", 1)
	with pytest.raises(optimistic.Unpredictable):
		optimistic.call_method(notes, "store")


def test_state_that_isnt_plain_data_stops_predictions():

	class Thing:

		def __add__(self, other):
			raise AssertionError("never run ahead of time")

	class Holder(t.div):

		thing = State(Thing())

		def render(self):
			return [t.button(on_click=self.bump) ["bump"]]

		def bump(self):
			self.thing = self.thing + 1

	holder = Holder()
	_, _, html, _ = serve(holder)

	assert "data-domino-predict" not in html
	assert "not plain data" in optimistic.explain(holder, holder.bump)


def test_runaway_loops_and_huge_values_stop_the_prediction_quickly():

	class Heavy(t.div):

		count = State(0)

		def render(self):
			return [t.p() [str(self.count)], t.button(on_click=self.loops) ["loops"], t.button(on_click=self.huge) ["huge"]]

		def loops(self):
			for _ in range(10000):
				for _ in range(10000):
					self.count += 1

		def huge(self):
			self.count = len("x" * 10 ** 12) + 2 ** 10 ** 9

	started = time.perf_counter()
	_, _, html, _ = serve(Heavy())

	assert "data-domino-predict" not in html
	assert time.perf_counter() - started < 2


shared = State([])


def test_changes_in_place_re_render_on_the_real_path(monkeypatch):

	class Writer(t.div):

		items = State([])

		def render(self):
			# A lambda that changes the list in place: not predicted, and returns nothing
			return [t.p() [str(len(self.items))], t.button(on_click=lambda: self.items.append("x")) ["add"]]

	class Reader(t.div):

		def render(self):
			return [t.p() [str(len(shared.value))]]

		def watch(self):
			shared.value.append(1)

	writer = Writer()
	app, client, html, page_id = serve(writer)
	page = app.page_store.pages[page_id]
	(add,) = [event_id for event_id, (element, _) in page.events.items() if element.__tag__ == "button"]

	data = client.post("/_domino/events", json={"page_id": page_id, "event_id": add}).get_json()

	assert writer.items == ["x"]
	assert data["id"] == writer.id() and "<p>\n        1\n    </p>" in data["html"]

	# A list in a shared State changed in place re-renders the components that show it
	refreshed = []
	monkeypatch.setattr(Reader, "refresh", lambda self, **kwargs: refreshed.append(self))
	reader = Reader()
	serve(reader)
	with reactive.batch(), reactive.tracking():
		reader.watch()
	assert refreshed == [reader]

	# Reading without changing re-renders nothing
	refreshed.clear()
	with reactive.batch(), reactive.tracking():
		len(shared.value)
	assert refreshed == []


def test_tracking_changes_in_place_costs_little():

	values = State(list(range(1000)))
	started = time.perf_counter()
	for _ in range(100):
		with reactive.tracking():
			values.value.append(1)
	per_event = (time.perf_counter() - started) / 100

	# Two marshal.dumps of a 1000-item list: about a tenth of a millisecond (allowing for slow machines)
	assert per_event < 0.005


def test_tracking_tells_changes_in_place_of_any_value():

	class Point:

		def __init__(self, x):
			self.x = x

		def __eq__(self, other):
			return isinstance(other, Point) and other.x == self.x

	for value, change in (
		([1, 2], lambda value: value.append(3)),
		({"a": [1]}, lambda value: value["a"].append(2)),
		({1, 2}, lambda value: value.discard(1)),
		([Point(1)], lambda value: setattr(value[0], "x", 2)),  # not marshal's: compared as a copy
	):
		state = State(value)
		changed = []
		state._dependency.changed = lambda: changed.append(1)
		with reactive.tracking():
			state.value
		assert changed == []
		with reactive.tracking():
			change(state.value)
		assert changed == [1], value


# Choices from a known set: event.value of a <select>, a checkbox, a radio button, a button


class Chooser(t.div):

	sort = State("new")
	done = State(False)
	size = State("m")
	last = State(None)
	query = State("")


	def render(self):

		return [
			t.select(on_change=self.choose)([t.option(value=value, selected=value == self.sort) [value.title()] for value in ("new", "old", "top")]),
			t.input(type="checkbox", checked=self.done, on_change=self.check),
			t.input(type="radio", name="size", value="l", on_change=lambda event: self.pick("l", event.value)),
			t.button(value="7", on_click=self.press) ["7"],
			t.input(name="q", on_input=self.search),
			t.p() [f"{self.sort} {self.done} {self.size} {self.last}"],
		]


	def choose(self, event):

		self.sort = event.value


	def check(self, event):

		self.done = event.value


	def pick(self, size, checked):

		if checked:
			self.size = size


	def press(self, event):

		self.last = event.value


	def search(self, event):

		self.query = event.value


def test_events_from_a_known_set_of_values_are_predicted_per_value():

	chooser = Chooser()
	graph = graph_of(chooser)
	edges = graph["edges"][0]

	# Keyed by the value as JSON, as core.js writes it
	select = edges["1-change"]["value"]
	assert set(select) == {'"new"', '"old"', '"top"'}
	assert select['"new"'] == 0  # what it shows already
	assert html_text(graph, select['"old"']).endswith("old False m None")
	assert html_text(graph, select['"top"']).endswith("top False m None")

	checkbox = edges["2-change"]["value"]
	assert set(checkbox) == {"true", "false"}
	assert html_text(graph, checkbox["true"]).endswith("new True m None") and checkbox["false"] == 0

	# A radio button only changes when it's checked; a button sends its value
	assert html_text(graph, edges["3-change"]["value"]["true"]).endswith("new False l None")
	assert html_text(graph, edges["4-click"]["value"]['"7"']).endswith("new False m 7")

	# Typing can be anything: up to the server
	assert "5-input" not in edges
	assert chooser.sort == "new" and chooser.done is False


def test_the_values_an_element_can_send():

	assert optimistic.choices_of(t.select()([t.option() ["  Two  words "], t.optgroup() [t.option(value=3) ["Three"]]])) == ["Two words", "3"]
	assert optimistic.choices_of(t.input(type="checkbox")) == [True, False]
	assert optimistic.choices_of(t.input(type="radio")) == [True]
	assert optimistic.choices_of(t.input(type="submit", value="Go")) == ["Go"]
	assert optimistic.choices_of(t.button()) == [None]
	assert optimistic.choices_of(t.div()) == [None]
	assert optimistic.choices_of(t.input()) is None
	assert optimistic.choices_of(t.input(type="email")) is None
	assert optimistic.choices_of(t.textarea()) is None
	# Too many to render each
	many = t.select()([t.option(value=number) [str(number)] for number in range(optimistic.MAX_CHOICES + 1)])
	assert optimistic.choices_of(many) is None


def test_explain_tells_which_elements_have_too_many_values():

	chooser = Chooser()
	serve(chooser)

	assert optimistic.explain(chooser, chooser.choose, t.select()([t.option() ["a"]])) is None
	assert "the <input> it's bound to can have any value" in optimistic.explain(chooser, chooser.search, t.input())


# Collections: writes kept aside, form fields filled in by the browser


tasks = Collection()


class Tasks(t.div):
	"""No State: everything it shows comes from the collection."""


	def render(self):

		return [
			t.form(on_submit=self.add) [
				t.input(name="text"),
				t.button(type="submit") ["Add"],
			],
			t.ul()([
				t.li() [
					t.input(type="checkbox", checked=task["done"], on_change=lambda event, id=task["_id"]: self.toggle(id)),
					t.span(title=task["text"]) [task["text"]],
					t.button(on_click=lambda event, id=task["_id"]: self.remove(id)) ["×"],
				]
				for task in tasks.find(sort="at")
			]),
			t.p() [f"{tasks.count({'done': False})} left"],
		]


	def add(self, event):

		text = event.form["text"].strip()
		if text:
			tasks.insert({"text": text, "done": False, "at": time.time()})


	def toggle(self, id):

		task = tasks.find_one({"_id": id})
		tasks.update({"_id": id}, {"$set": {"done": not task["done"]}})


	def remove(self, id):

		tasks.remove({"_id": id})


@pytest.fixture
def two_tasks():

	tasks.remove({})
	first = tasks.insert({"text": "Write tests", "done": False, "at": 1})
	second = tasks.insert({"text": "Ship it", "done": True, "at": 2})

	yield first, second

	tasks.remove({})


def marker(slot, changes=""):

	return f"{optimistic.OPEN}{slot}{changes}{optimistic.CLOSE}"


def test_collection_writes_are_predicted_and_never_made(two_tasks):

	graph = graph_of(Tasks())
	edges = graph["edges"][0]

	# Nothing was written
	assert [task["text"] for task in tasks.find(sort="at")] == ["Write tests", "Ship it"]

	# The new task's text is the form field's placeholder, stripped, in the text and the attribute
	submit = edges["1-submit"]
	assert submit["form"] == {"text": 0}
	added = html_of(graph, submit["to"])
	assert f'<span title="{marker(0, "s")}">' in added and added.count(marker(0, "s")) == 2
	assert "2 left" in html_text(graph, submit["to"])

	# Each task's checkbox and remove button, by its _id
	assert html_text(graph, edges["2-change"]).endswith("0 left")
	assert "Write tests" not in html_of(graph, edges["3-click"]) and "Ship it" in html_of(graph, edges["3-click"])
	assert html_text(graph, edges["4-change"]).endswith("2 left")
	assert "Ship it" not in html_of(graph, edges["5-click"])


def test_a_form_submitted_again_before_the_answer_is_predicted_too(two_tasks):

	graph = graph_of(Tasks())

	first = graph["edges"][0]["1-submit"]
	second = graph["edges"][first["to"]]["1-submit"]
	third = graph["edges"][second["to"]]["1-submit"]

	# Each submission's text has a placeholder of its own
	assert second["form"] == {"text": 1} and third["form"] == {"text": 2}
	assert all(marker(slot, "s") in html_of(graph, third["to"]) for slot in range(3))
	# Twice more (CHAIN), not forever; and nothing else from those states
	assert third["to"] >= len(graph["edges"]) or graph["edges"][third["to"]] == {}
	assert set(graph["edges"][first["to"]]) == {"1-submit"}


def test_placeholders_allow_only_what_the_browser_can_redo():

	field = optimistic.Placeholder(4)

	assert field.strip().lower()[:5].upper() == marker(4, "slt5;u")
	assert f"<b>{field}</b>" == f"<b>{marker(4)}</b>"
	assert str(escape(field)) == marker(4)
	assert len(field) == 1 and field  # counts as typed in (the browser predicts only then)
	assert deepcopy(field) is field

	for refused in (
		lambda: field.replace("a", "b"), lambda: int(field), lambda: "a" in field, lambda: list(field),
		lambda: field * 2, lambda: field % (), lambda: field[1], lambda: f"{field:>5}", lambda: field.split(),
		lambda: field.strip("x"), lambda: field.startswith("a"),
	):
		with pytest.raises((optimistic.Unpredictable, ValueError)):
			refused()


def test_form_handlers_that_do_more_with_the_text_are_not_predicted():

	class Numbers(t.div):

		total = State(0)

		def render(self):
			return [t.form(on_submit=self.add) [t.input(name="n")], t.p() [str(self.total)]]

		def add(self, event):
			self.total += int(event.form["n"])

	# int() of what's typed can't be worked out ahead
	_, _, html, _ = serve(Numbers())

	assert "data-domino-predict" not in html


def test_predicted_reads_see_the_writes_kept_aside():

	books = Collection()
	books.insert({"_id": "a", "title": "A", "year": 2001, "read": False})
	books.insert({"_id": "b", "title": "B", "year": 1999, "read": True})
	books.insert({"_id": "c", "title": "C", "year": 2010, "read": False})

	overlay = {reactive.DATA: ()}
	with reactive.predicting(overlay):
		books.insert({"title": "D", "year": 2005, "read": False})
		assert books.update({"_id": "b"}, {"$set": {"read": False}}) == 1
		assert books.remove({"_id": "c"}) == 1
		unread = [book["title"] for book in books.find({"read": False}, sort=[("year", -1)], limit=2)]
		count = books.count()

	# The new one sorted in, "b" brought into the query by its update, "c" gone, the limit kept
	assert unread == ["D", "A"]
	assert count == 3
	assert overlay[reactive.DATA][0][1][1]["_id"] == "predicted-0"
	# Nothing real changed
	assert [book["title"] for book in books.find(sort="title")] == ["A", "B", "C"]
	assert books.find_one({"_id": "b"})["read"] is True

	# A write outside a prediction of data (a render that writes, say) is dropped
	with reactive.predicting({}):
		books.insert({"title": "E"})
	assert books.count() == 3


def test_many_items_are_capped_and_sent_as_patches(two_tasks):

	tasks.remove({})
	for number in range(60):
		tasks.insert({"text": f"Task number {number} " + "x" * 40, "done": False, "at": number})

	started = time.perf_counter()
	graph = graph_of(Tasks())
	elapsed = time.perf_counter() - started

	# At most MAX_PREDICTIONS states besides the current one, large ones as patches
	assert len(graph["states"]) <= optimistic.MAX_PREDICTIONS + 2
	assert "base" in graph and sum(isinstance(state, list) for state in graph["states"]) >= 10
	assert len(optimistic.script_json(graph)) < optimistic.MAX_BYTES + 8000
	assert elapsed < 2


# In MongoDB (connects on first use)
stored = Collection(f"test_{uuid.uuid4().hex[:8]}")


@pytest.mark.mongo
def test_predictions_read_mongodb_and_never_write_to_it():

	stored.insert({"text": "Stored", "done": False, "at": 1})

	class StoredTasks(t.div):

		def render(self):
			return [
				t.form(on_submit=self.add) [t.input(name="text")],
				t.ul()([
					t.li() [task["text"], t.button(on_click=lambda event, id=task["_id"]: self.remove(id)) ["×"]]
					for task in stored.find(sort="at")
				]),
			]

		def add(self, event):
			stored.insert({"text": event.form["text"], "done": False, "at": time.time()})

		def remove(self, id):
			stored.remove({"_id": id})

	graph = graph_of(StoredTasks())
	edges = graph["edges"][0]

	assert marker(0) in html_of(graph, edges["1-submit"]["to"]) and "Stored" in html_text(graph, edges["1-submit"]["to"])
	assert "Stored" not in html_text(graph, edges["2-click"])
	reactive.wait()
	assert [task["text"] for task in stored.find()] == ["Stored"]
