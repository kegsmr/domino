"""Developer tools: only in debug mode, and nothing of them outside it.

Page tests run apps with app.testing = True, where errors must reach the test, so these tests
turn app.debug on themselves and use Flask's test client."""

import logging
import re
import sys
import types

import pytest

import domino.tags as t
from domino import Collection, Domino, State, template
from domino import _optimistic as optimistic
from domino import Document
from domino._devtools import startup_warnings
from domino.mongo import MongoNotConfigured


UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class Inner(t.p):


	def render(self):

		raise RuntimeError("<script>alert('x')</script> broke")


class Outer(t.section):


	def render(self):

		return [
			t.h2() ["Outer"],
			Inner()
		]


class Counter(t.div):

	count = State(0)


	def render(self):

		return [
			t.p() [f"Count: {self.count}"],
			t.button(on_click=self.increment) ["+"],
			t.button(on_click=self.save) ["Save"],
		]


	def increment(self):

		self.count += 1


	def save(self, event):

		self.count = int(event.value or 0)


class Failing(t.div):


	def render(self):

		return [
			t.button(on_click=self.fail) ["Fail"]
		]


	def fail(self):

		raise ValueError("handler <b>broke</b>")


def make_app(make, debug=True):

	app = Domino(__name__)
	app.debug = debug

	@app.route("/")
	def index():
		return Document() [
			make()
		]

	return app


def page_ids(html):

	page_id = html.split('data-domino-page="')[1].split('"')[0]
	event_ids = re.findall(r'data-event-id="([^"]+)"', html)

	return page_id, event_ids


def click(client, page_id, event_id, data=None):

	return client.post("/_domino/events", json={"page_id": page_id, "event_id": event_id, "data": data or {}})


# The error page


def test_debug_error_page_shows_the_error_frames_and_component_stack(caplog):

	client = make_app(Outer).test_client()

	with caplog.at_level(logging.ERROR):
		response = client.get("/?q=<x>")
	html = response.get_data(as_text=True)

	assert response.status_code == 500
	assert response.mimetype == "text/html"
	assert '<p class="kind">RuntimeError</p>' in html
	# Everything from the error is escaped
	assert "&lt;script&gt;alert(&#39;x&#39;)&lt;/script&gt; broke" in html
	assert "<script>alert" not in html
	assert "<x>" not in html and "q=&lt;x&gt;" in html
	# The frame that raised, with its source, marked as the app's own; libraries' are folded
	assert 'data-app="true"' in html and 'data-app="false"' in html
	assert "Inner.render" in html
	assert "raise RuntimeError(&#34;&lt;script&gt;" in html or "raise RuntimeError(&quot;&lt;script&gt;" in html
	assert '<details class="library">' in html
	assert re.search(r'<ol class="path"><li>Outer</li><li class=failed>Inner</li></ol>', html)
	assert "GET" in html and "Plain traceback" in html
	# Logged as usual
	assert any(record.exc_info for record in caplog.records)


def test_error_page_marks_the_current_line():

	html = make_app(Outer).test_client().get("/").get_data(as_text=True)

	current = re.findall(r'<div class="current"><span class="number">\d+</span>([^<]*)</div>', html)
	assert any("raise RuntimeError" in line for line in current)


def test_without_debug_the_error_has_no_details(caplog):

	client = make_app(Outer, debug=False).test_client()

	with caplog.at_level(logging.ERROR):
		response = client.get("/")
	html = response.get_data(as_text=True)

	assert response.status_code == 500
	assert "broke" not in html and "Inner" not in html and "Traceback" not in html
	assert "Internal Server Error" in html


def test_tests_still_get_the_exception():

	app = make_app(Outer)
	app.testing = True

	with pytest.raises(RuntimeError, match="broke"):
		app.test_client().get("/")


def test_hints_for_mongo_and_non_elements():

	class NeedsMongo(t.div):

		def render(self):
			raise MongoNotConfigured("no MongoDB")

	class ReturnsDict(t.div):

		def render(self):
			return [{"score": 3}]

	mongo = make_app(NeedsMongo).test_client().get("/").get_data(as_text=True)
	child = make_app(ReturnsDict).test_client().get("/").get_data(as_text=True)

	assert "mongo.url" in mongo and "Collection() without a name" in mongo
	assert "Invalid child" in child and "isn&#39;t an element" in child
	assert re.search(r"<li class=failed>ReturnsDict</li>", child)
	assert "while rendering ReturnsDict" in child


def test_template_syntax_errors_show_the_template_line(tmp_path):

	(tmp_path / "broken.html").write_text("<h1>{{ title }}</h1>\n<p>\n{% if title %}\n<b>never closed</b>\n", encoding="utf-8")
	app = Domino("devtools_template_app", root_path=str(tmp_path), pages=False)
	app.debug = True

	@app.route("/")
	def index():
		return template("broken.html", title="Hi")

	html = app.test_client().get("/").get_data(as_text=True)

	assert "TemplateSyntaxError" in html
	assert '<section class="template">' in html
	assert "broken.html, line" in html
	assert "{% if title %}" in html


def test_example_pages_whose_render_fails(load_example):

	client = load_example("devtools").app.test_client()
	client.application.debug = True

	render = client.get("/broken/render").get_data(as_text=True)
	child = client.get("/broken/child").get_data(as_text=True)
	jinja = client.get("/broken/template").get_data(as_text=True)

	assert "ZeroDivisionError" in render
	assert re.search(r"<li>Layout</li><li>Report</li><li class=failed>Average</li>", render)
	assert "components/report.py:" in render and "len(self.scores)" in render
	assert "Invalid child" in child and "Mistake" in child
	assert "UndefinedError" in jinja and "components/greeting.html:3" in jinja
	assert '<span class="badge">template</span>' in jinja and "inbox.unread" in jinja

	client.application.debug = False
	assert "ZeroDivisionError" not in client.get("/broken/render").get_data(as_text=True)


# Event errors


def test_event_error_has_structured_frames_in_debug(caplog):

	client = make_app(Failing).test_client()
	page_id, (event_id,) = page_ids(client.get("/").get_data(as_text=True))

	with caplog.at_level(logging.ERROR):
		data = click(client, page_id, event_id).get_json()

	assert data["error"] == "ValueError: handler <b>broke</b>"
	assert "Traceback" in data["traceback"]
	assert data["handler"] == "Failing.fail"
	frames = data["frames"]
	app_frames = [frame for frame in frames if frame["app"]]
	assert app_frames[-1]["function"] == "Failing.fail"
	assert app_frames[-1]["file"] == "test_devtools.py"
	assert any("raise ValueError" in text for number, text in app_frames[-1]["context"] if number == app_frames[-1]["line"])
	assert any(not frame["app"] and frame["file"].startswith("domino/") for frame in frames)
	assert data["components"] == [] and data["hints"] == []
	assert isinstance(data["debug_ms"], float)


def test_event_error_from_a_render_has_the_component_stack(caplog):

	class Breaks(t.div):

		broken = State(False)

		def render(self):
			if self.broken:
				return [Inner()]
			return [t.button(on_click=self.toggle) ["Break"]]

		def toggle(self):
			self.broken = True

	client = make_app(Breaks).test_client()
	page_id, (event_id,) = page_ids(client.get("/").get_data(as_text=True))

	with caplog.at_level(logging.ERROR):
		data = click(client, page_id, event_id).get_json()

	assert data["components"] == ["Breaks", "Inner"]


@pytest.mark.parametrize("testing", [False, True])
def test_event_error_has_no_frames_outside_debug(caplog, testing):

	app = make_app(Failing, debug=False)
	app.testing = testing
	client = app.test_client()
	page_id, (event_id,) = page_ids(client.get("/").get_data(as_text=True))

	with caplog.at_level(logging.ERROR):
		data = click(client, page_id, event_id).get_json()

	assert "frames" not in data and "components" not in data and "debug_ms" not in data
	# Page tests still get the traceback, as before
	assert ("traceback" in data) is testing


def test_event_responses_carry_timing_only_in_debug():

	for debug in (True, False):
		client = make_app(Counter, debug=debug).test_client()
		page_id, event_ids = page_ids(client.get("/").get_data(as_text=True))
		data = click(client, page_id, event_ids[0]).get_json()

		assert "Count: 1" in data["html"]
		assert ("debug_ms" in data) is debug
		assert ("debug_handler" in data) is debug
		if debug:
			assert data["debug_handler"] == "Counter.increment"
			assert data["debug_ms"] >= 0


# The inspector's data


def inspect(client, page_id, what, **params):

	return client.get(f"/_domino/debug/{what}", query_string=params, headers={"X-Domino-Page": page_id} if page_id else {})


def test_inspect_gives_state_events_and_predictions():

	client = make_app(Counter).test_client()
	page_id, event_ids = page_ids(client.get("/").get_data(as_text=True))

	components = inspect(client, page_id, "components").get_json()["components"]
	(counter,) = [item for item in components if item["class"] == "Counter"]

	data = inspect(client, page_id, "inspect", id=counter["id"]).get_json()

	assert data["class"] == "Counter"
	assert data["file"] == "test_devtools.py" and data["line"] > 0
	assert data["state"] == [{"name": "count", "value": "0"}]
	assert data["subscriptions"] == ["self.count (State)"]
	events = {event["handler"]: event for event in data["events"]}
	assert events["Counter.increment"]["predicted"] is True
	assert events["Counter.increment"]["reason"] is None
	assert events["Counter.increment"]["event"] == "click"
	assert events["Counter.increment"]["element"].startswith("<button>")
	assert events["Counter.save"]["predicted"] is False
	assert "reads the event" in events["Counter.save"]["reason"]

	# Live: the State as it is now
	click(client, page_id, event_ids[0])
	data = inspect(client, page_id, "inspect", id=counter["id"]).get_json()
	assert data["state"] == [{"name": "count", "value": "1"}]


def test_inspect_lists_ancestors_and_children(load_example):

	client = load_example("devtools").app.test_client()
	client.application.debug = True
	page_id, _ = page_ids(client.get("/").get_data(as_text=True))

	components = inspect(client, page_id, "components").get_json()["components"]
	classes = [item["class"] for item in components]
	assert {"Layout", "Counter", "TodoList", "TodoItem", "Crash"} <= set(classes)

	item = next(item for item in components if item["class"] == "TodoItem")
	data = inspect(client, page_id, "inspect", id=item["id"]).get_json()
	assert [ancestor["class"] for ancestor in data["ancestors"]] == ["Layout", "TodoList"]
	assert all(not event["predicted"] for event in data["events"])
	assert "TodoList" in data["events"][0]["reason"]

	todo = data["ancestors"][-1]
	data = inspect(client, page_id, "inspect", id=todo["id"]).get_json()
	assert [child["class"] for child in data["children"]] == ["TodoItem"]
	assert [state["name"] for state in data["state"]] == ["items", "show"]


def test_inspect_refuses_other_pages_components():

	client = make_app(Counter).test_client()
	first, _ = page_ids(client.get("/").get_data(as_text=True))
	second, _ = page_ids(client.get("/").get_data(as_text=True))
	(other,) = [item for item in inspect(client, second, "components").get_json()["components"] if item["class"] == "Counter"]

	assert inspect(client, second, "inspect", id=other["id"]).status_code == 200
	assert inspect(client, first, "inspect", id=other["id"]).status_code == 404
	assert inspect(client, None, "inspect", id=other["id"]).status_code == 404
	assert inspect(client, "nope", "components").status_code == 404


def test_debug_endpoints_are_absent_outside_debug():

	client = make_app(Counter, debug=False).test_client()
	page_id, _ = page_ids(client.get("/").get_data(as_text=True))

	assert inspect(client, page_id, "components").status_code == 404
	assert client.get("/_domino/debug.js").status_code == 404


def test_debug_js_is_only_served_and_linked_in_debug():

	app = make_app(Counter)
	client = app.test_client()

	html = client.get("/").get_data(as_text=True)
	script = client.get("/_domino/debug.js")
	assert '<script src="/_domino/debug.js" defer>' in html
	assert script.status_code == 200 and script.mimetype == "text/javascript"
	assert "Domino.devtools" in script.get_data(as_text=True)

	app.debug = False
	assert "debug.js" not in client.get("/").get_data(as_text=True)


@pytest.mark.parametrize("example", ["counter", "todo", "devtools", "instant", "templating"])
def test_production_pages_have_nothing_of_the_devtools(load_example, example):

	app = load_example(example).app
	client = app.test_client()
	production = UUID.sub("<id>", client.get("/").get_data(as_text=True))

	app.debug = True
	debug = UUID.sub("<id>", client.get("/").get_data(as_text=True))
	app.debug = False
	again = UUID.sub("<id>", client.get("/").get_data(as_text=True))

	# Debug pages differ only by the script that loads the tools, and production pages are the same after
	line = re.search(r"\n[ \t]*<script src=\"/_domino/debug.js\" defer>\s*</script>", debug).group(0)
	assert debug.replace(line, "", 1) == production
	assert again == production
	assert "/_domino/debug" not in production and "domino-devtools" not in production


# Explaining predictions


class Explained(t.div):

	count = State(0)


	def render(self):

		return []


	def plain(self):

		self.count += 1


	def uses_event(self, event):

		self.count = event.value


	def writes(self):

		print("side effect")
		self.count += 1


	def returns(self):

		return self


def test_explain_says_why_a_handler_isnt_predicted():

	component = Explained()
	other = Explained()

	assert optimistic.explain(component, component.plain) is None
	assert "reads the event" in optimistic.explain(component, component.uses_event)
	assert "calls print()" in optimistic.explain(component, component.writes)
	assert "line" in optimistic.explain(component, component.writes)
	assert "returns a value" in optimistic.explain(component, component.returns)
	assert "a method of another Explained" in optimistic.explain(component, other.plain)
	assert "a method of Explained, not of Counter" in optimistic.explain(Counter(), other.plain)
	call_other = lambda: other.plain()
	assert "calls other.plain() of Explained, not a method of this Explained" in optimistic.explain(component, call_other)

	class Off(Explained):
		optimistic = False

	off = Off()
	assert "optimistic = False" in optimistic.explain(off, off.plain)


# Startup warnings


def test_startup_warns_about_in_memory_collections(tmp_path, caplog):

	app = Domino("devtools_warning_app", root_path=str(tmp_path), pages=False)
	module = types.ModuleType("devtools_warning_data")
	module.__file__ = str(tmp_path / "data.py")
	module.notes = Collection()
	sys.modules[module.__name__] = module
	try:
		with caplog.at_level(logging.WARNING):
			startup_warnings(app)
			startup_warnings(app)
	finally:
		del sys.modules[module.__name__]

	warnings = [record.getMessage() for record in caplog.records if "Collection()" in record.getMessage()]
	assert len(warnings) == 1
	assert "data.py: notes = Collection()" in warnings[0] and "--workers" in warnings[0]
