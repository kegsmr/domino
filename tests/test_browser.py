"""End-to-end tests of core.js in a real browser. Skipped when Playwright isn't installed."""

import json
import os
import re
import struct
import sys
import threading
import time
import zlib

import pytest

playwright = pytest.importorskip("playwright.sync_api")

from werkzeug.serving import make_server

from conftest import EXAMPLES, MONGO_URL, Served


@pytest.fixture(scope="module")
def browser():

	with playwright.sync_playwright() as p:
		browser = p.chromium.launch()
		yield browser
		browser.close()


@pytest.fixture
def serve_wsgi(load_example):
	"""Serves an example as plain WSGI (like gunicorn), so pages use POST + Server-Sent Events."""

	servers = []

	def start(name, patch=None):
		# examples/<name>/app.py, registered in sys.modules so Flask finds its folder
		module = load_example(name)
		if patch:
			patch(module)
		server = make_server("127.0.0.1", 0, module.app, threaded=True)
		threading.Thread(target=server.serve_forever, daemon=True).start()
		servers.append(server)
		return f"http://127.0.0.1:{server.server_port}/"

	yield start

	for server in servers:
		server.shutdown()


@pytest.fixture
def serve_asgi(asgi_server, load_example):
	"""Serves an example with uvicorn (app.asgi), so pages use one WebSocket."""

	def start(name, patch=None):
		# examples/<name>/app.py, registered in sys.modules so Flask finds its folder
		module = load_example(name)
		if patch:
			patch(module)
		return asgi_server(module.app).url

	return start


@pytest.fixture(params=["wsgi", "asgi"])
def serve(request, serve_wsgi, serve_asgi):
	"""Runs the test on both transports."""

	if request.param == "wsgi":
		return serve_wsgi

	return serve_asgi


def sent_events(page):
	"""Events the page sends to the server, over HTTP or the WebSocket."""

	sent = []

	def on_frame(payload):
		if isinstance(payload, str) and json.loads(payload).get("type") == "event":
			sent.append(payload)

	page.on("request", lambda request: request.method == "POST" and "/_domino/events" in request.url and sent.append(request))
	page.on("websocket", lambda ws: ws.on("framesent", on_frame))

	return sent


@pytest.fixture
def page(browser):

	page = browser.new_page()
	page.errors = []
	page.on("console", lambda message: message.type == "error" and page.errors.append(message.text))
	page.on("pageerror", lambda error: page.errors.append(str(error)))
	yield page
	page.close()


def test_rapid_clicks_all_count(serve, page):

	page.goto(serve("counter"))
	page.evaluate("() => { const button = document.querySelector('button'); for (let i = 0; i < 10; i++) button.click(); }")

	page.wait_for_function("document.querySelector('p').textContent.includes('10')")
	assert page.errors == []


def test_todo_submit_clears_input_and_removal_keeps_checkboxes_right(serve, page):

	page.goto(serve("todo"))
	for text in ["one", "two", "three"]:
		page.fill("input[name=text]", text)
		page.press("input[name=text]", "Enter")
		page.wait_for_function(f"document.querySelectorAll('li').length >= {['one', 'two', 'three'].index(text) + 1}")

	assert page.input_value("input[name=text]") == ""

	# click, not check(): the box is reset as soon as the item is removed
	page.locator("li input[type=checkbox]").nth(1).click()
	page.wait_for_function("document.querySelectorAll('li').length === 2")

	assert [text.strip() for text in page.locator("li").all_inner_texts()] == ["one", "three"]
	assert page.locator("li input:checked").count() == 0
	assert page.errors == []


def test_partial_update_keeps_other_fields(serve, page):

	page.goto(serve("forms"))
	page.fill("input[name=email]", "ada@example.com")
	page.select_option("select[name=plan]", "Team")
	page.locator("input[name=seats]").fill("7")

	page.wait_for_function("document.querySelector('output').textContent.includes('7')")
	assert page.input_value("input[name=email]") == "ada@example.com"
	assert page.input_value("select[name=plan]") == "Team"


def test_form_checks_in_the_browser_then_on_the_server(serve, page):

	# Listening before the page opens its WebSocket, so its frames are all seen
	sent = sent_events(page)
	page.goto(serve("forms"))

	# The browser's own check stops an empty required field; nothing is sent
	page.click("button[type=submit]")
	page.wait_for_timeout(300)
	assert sent == []
	assert page.evaluate("document.querySelector('input[name=name]').validity.valueMissing")

	# Only the server knows the email is taken
	page.fill("input[name=name]", "Ada")
	page.fill("input[name=email]", "taken@example.com")
	page.fill("input[name=age]", "36")
	page.select_option("select[name=plan]", "Pro")
	page.check("input[name=newsletter]")
	page.fill("input[name=password]", "analytical")
	page.fill("input[name=confirm]", "analytical")
	page.click("button[type=submit]")

	page.wait_for_selector("[role=alert]:has-text('That email is already registered.')")
	assert page.get_attribute("input[name=email]", "aria-invalid") == "true"
	assert page.input_value("input[name=name]") == "Ada"
	assert page.input_value("input[name=email]") == "taken@example.com"
	assert page.input_value("input[name=age]") == "36"
	assert page.input_value("select[name=plan]") == "Pro"
	assert page.is_checked("input[name=newsletter]")
	assert len(sent) >= 1

	page.fill("input[name=email]", "ada@example.com")
	page.fill("input[name=password]", "analytical")
	page.fill("input[name=confirm]", "analytical")
	page.click("button[type=submit]")

	page.wait_for_selector("h2:has-text('Welcome, Ada!')")
	assert "36 (int)" in page.inner_text("dl")
	assert "True (bool)" in page.inner_text("dl")
	assert page.errors == []


def test_debounced_search_keeps_focus_and_typing(serve, page):

	def slow(module):
		# The example's own components package, just imported with its app
		from components.search import Search
		search = Search.search

		def delayed(self, event):
			time.sleep(0.3)
			return search(self, event)

		Search.search = delayed

	sent = sent_events(page)
	page.goto(serve("search", slow))
	box = page.locator("input[type=search]")

	box.click()
	box.press_sequentially("ru", delay=30)
	page.wait_for_timeout(400)  # the first request is now in flight
	box.press_sequentially("st", delay=30)
	page.wait_for_function("document.querySelector('p').textContent.trim().startsWith('1 match')", timeout=5000)

	assert box.input_value() == "rust"
	assert page.evaluate("document.activeElement.type") == "search"
	assert page.evaluate("document.activeElement.selectionStart") == 4
	assert page.locator("li").all_inner_texts() == ["Rust"]
	assert len(sent) == 2
	assert page.errors == []


def test_server_push_updates_the_clock_without_user_action(serve, page):

	page.goto(serve("clock"))
	first = page.locator("p").inner_text()

	page.wait_for_function(f"document.querySelector('p').textContent.trim() !== {first!r}", timeout=5000)
	assert page.errors == []


@pytest.mark.mongo
def test_reactive_chat_updates_other_windows_and_keeps_their_typing(serve, browser):

	# Each transport's run starts with no messages (the database is shared by the test run)
	def clear_messages(module):
		from data import messages
		messages.remove({})

	url = serve("chat", clear_messages)
	windows = [browser.new_page(), browser.new_page()]
	errors = []
	for window in windows:
		window.on("pageerror", lambda error: errors.append(str(error)))
		window.goto(url)
	first, second = windows

	first.fill("input[name=name]", "Ada")
	first.fill("input[name=text]", "Hi")
	first.press("input[name=text]", "Enter")
	second.wait_for_function("document.querySelectorAll('.messages li').length === 1", timeout=5000)

	second.fill("input[name=text]", "half-typed")
	first.fill("input[name=text]", "Again")
	first.press("input[name=text]", "Enter")
	second.wait_for_function("document.querySelectorAll('.messages li').length === 2", timeout=5000)
	# The other window can get the push before this one has applied its own response
	first.wait_for_function("document.querySelector('input[name=text]').value === ''", timeout=5000)

	assert second.input_value("input[name=text]") == "half-typed"
	assert first.input_value("input[name=name]") == "Ada"
	assert first.input_value("input[name=text]") == ""
	assert errors == []

	for window in windows:
		window.close()


def test_public_settings_reach_the_browser(serve, page):

	page.goto(serve("settings"))

	settings = page.evaluate("() => window.Domino.settings")
	assert settings == {"greeting": "Hello from settings.json", "theme_color": "#2a6fdb"}
	assert page.locator("#greeting").inner_text() == "Hello from settings.json"
	assert page.locator("h1").inner_text() == "Settings example"
	assert page.errors == []


def test_button_is_busy_while_its_event_is_in_flight(serve, page):

	page.goto(serve("loading"))
	save = page.locator("button.save")

	save.click()
	page.wait_for_selector("html[data-domino-loading]")
	assert save.get_attribute("aria-busy") == "true"
	assert save.get_attribute("data-loading") == ""
	# Only form submits disable their buttons; other clicks all count
	assert save.is_enabled()

	page.wait_for_function("document.querySelector('p').textContent.includes('Saved 1')", timeout=5000)
	assert save.get_attribute("aria-busy") is None
	assert save.get_attribute("data-loading") is None
	assert save.is_enabled()
	assert page.evaluate("document.documentElement.hasAttribute('data-domino-loading')") is False
	assert page.errors == []


def test_already_disabled_buttons_stay_disabled(serve_wsgi, page):

	# A response that updates nothing, so only the busy marks touch the button
	page.goto(serve_wsgi("counter"))
	page.route("**/_domino/events", lambda route: route.fulfill(json={"id": None, "html": None}))
	page.evaluate("""() => {
		const button = document.querySelector('button');
		button.disabled = true;
		window.done = Domino.triggerEvent(button.dataset.eventId, {}, null, button);
	}""")

	page.evaluate("window.done")
	assert page.evaluate("document.querySelector('button').disabled") is True
	assert page.locator("button[data-loading]").count() == 0
	assert page.errors == []


def test_debounced_input_is_marked_but_not_disabled(serve, page):

	def slow(module):
		from components.search import Search
		search = Search.search

		def delayed(self, event):
			time.sleep(0.5)
			return search(self, event)

		Search.search = delayed

	page.goto(serve("search", slow))
	box = page.locator("input[type=search]")

	box.click()
	box.press_sequentially("ru", delay=30)
	page.wait_for_selector("input[data-loading][aria-busy=true]", timeout=2000)
	assert box.is_enabled()
	assert page.evaluate("document.activeElement.type") == "search"

	page.wait_for_function("!document.documentElement.hasAttribute('data-domino-loading')", timeout=5000)
	assert box.get_attribute("data-loading") is None
	assert page.errors == []


def unexpected(errors):

	# The intentional 500 shows up as a failed resource load and as our console.error
	return [error for error in errors if "500" not in error and "Domino event error" not in error]


def debug(module):

	module.app.debug = True


def test_debug_error_shows_overlay(serve, page):

	page.goto(serve("loading", debug))

	page.get_by_text("Raise an exception").click()
	overlay = page.locator("#domino-error")
	overlay.wait_for(timeout=5000)

	assert "RuntimeError: Something went wrong while saving" in overlay.inner_text()
	# Folded under the frames debug.js shows (see test_overlay_shows_frames_for_a_failing_handler)
	assert "Traceback" in overlay.locator("pre").text_content()
	assert any("Domino event error" in error for error in page.errors)
	assert unexpected(page.errors) == []

	# The button works again, and the overlay can be closed
	assert page.get_by_role("button", name="Raise an exception").is_enabled()
	overlay.get_by_role("button", name="Close").click()
	assert page.locator("#domino-error").count() == 0


def test_production_error_logs_only(serve, page):

	page.goto(serve("loading"))

	page.get_by_text("Raise an exception").click()
	page.wait_for_function("!document.documentElement.hasAttribute('data-domino-loading')", timeout=5000)

	assert page.locator("#domino-error").count() == 0
	assert any("Domino event error" in error for error in page.errors)
	assert not any("Something went wrong" in error for error in page.errors)
	assert unexpected(page.errors) == []


def test_cancelled_error_event_shows_nothing(serve, page):

	page.goto(serve("loading", debug))
	page.evaluate("""() => document.addEventListener('domino:error', (e) => {
		window.caught = e.detail;
		e.preventDefault();
	})""")

	page.get_by_text("Raise an exception").click()
	page.wait_for_function("window.caught", timeout=5000)

	assert "Something went wrong" in page.evaluate("window.caught.error")
	assert page.evaluate("window.caught.eventId").endswith("-click")
	assert page.locator("#domino-error").count() == 0
	assert unexpected(page.errors) == []


def test_overlay_shows_frames_for_a_failing_handler(serve, page):

	page.goto(serve("devtools", debug))

	page.get_by_text("Raise an exception").click()
	overlay = page.locator("#domino-error")
	overlay.wait_for(timeout=5000)
	text = overlay.inner_text()

	# The error, which element fired which handler, and a hint
	assert "KeyError: 'name'" in text
	assert 'click on button.crash "Raise an exception" → Crash.save' in text
	assert "event.form.get(" in text

	# The app's own frame open, with its source and the line that raised; Domino's folded
	frame = overlay.locator(".dt-frame[data-app=true]")
	assert frame.count() == 1
	assert re.search(r"Crash\.save\s+components/crash\.py:\d+", frame.inner_text())
	assert frame.locator(".dt-current").inner_text().strip().endswith('name = event.form["name"]')
	assert overlay.locator("details.dt-library .dt-frame[data-app=false]").count() >= 1

	# Still dismissable, with Esc too
	page.keyboard.press("Escape")
	assert page.locator("#domino-error").count() == 0
	assert unexpected(page.errors) == []


def test_inspector_picks_a_component_and_follows_its_state(serve, page):

	page.goto(serve("devtools", debug))
	counter = page.locator("section.Counter")

	page.keyboard.press("Alt+Shift+D")
	panel = page.locator("#domino-inspector")
	panel.wait_for(timeout=5000)
	assert page.evaluate("document.documentElement.hasAttribute('data-domino-inspecting')")
	page.wait_for_function("Domino.devtools.inspector.components.size > 0", timeout=5000)

	# Hovering outlines the component under the cursor, with its class name
	counter.locator("h2").hover()
	highlight = page.locator("#domino-highlight")
	page.wait_for_function("getComputedStyle(document.getElementById('domino-highlight')).display === 'block'", timeout=5000)
	assert highlight.inner_text().startswith("Counter")
	outlined, actual = highlight.bounding_box(), counter.bounding_box()
	assert all(abs(outlined[key] - actual[key]) < 1 for key in ("x", "y", "width", "height"))

	# Clicking pins the panel, and doesn't reach the page's own events
	counter.get_by_role("button", name="+1").click()
	page.wait_for_function("document.querySelector('#domino-inspector .dt-name') !== null", timeout=5000)
	assert panel.locator(".dt-name").inner_text().startswith("Counter")
	assert counter.locator("p").inner_text() == "Count: 0"
	assert not page.evaluate("document.documentElement.hasAttribute('data-domino-inspecting')")
	assert panel.locator("td.dt-key").all_inner_texts() == ["count", "step"]
	assert panel.locator("td.dt-value").all_inner_texts() == ["0", "1"]
	assert "Counter.increment" in panel.inner_text() and "instant" in panel.inner_text()

	# The State follows the component as it's clicked
	counter.get_by_role("button", name="+1").click()
	counter.get_by_role("button", name="Bigger steps").click()
	page.wait_for_function("Array.from(document.querySelectorAll('#domino-inspector td.dt-value')).map((td) => td.textContent).join() === '1,10'", timeout=5000)

	# Its parent, by its breadcrumb
	panel.locator(".dt-crumb", has_text="Layout").click()
	page.wait_for_function("document.querySelector('#domino-inspector .dt-name').textContent.startsWith('Layout')", timeout=5000)

	# The shortcut toggles picking
	page.keyboard.press("Alt+Shift+D")
	assert page.evaluate("document.documentElement.hasAttribute('data-domino-inspecting')")
	page.keyboard.press("Alt+Shift+D")
	assert not page.evaluate("document.documentElement.hasAttribute('data-domino-inspecting')")
	assert page.errors == []


def test_event_log_lists_events_with_timings(serve, page):

	page.goto(serve("devtools", debug))

	page.get_by_role("button", name="+1").click()
	page.wait_for_function("document.querySelector('section.Counter p').textContent.trim() === 'Count: 1'", timeout=5000)
	page.fill("input[name=text]", "Write tests")
	page.press("input[name=text]", "Enter")
	page.wait_for_function("document.querySelectorAll('li.TodoItem').length === 2", timeout=5000)
	page.wait_for_function("Domino.devtools.log.every((entry) => entry.status !== null)", timeout=5000)

	page.evaluate("Domino.inspect()")
	page.keyboard.press("Escape")
	panel = page.locator("#domino-inspector")
	panel.locator(".dt-tab", has_text="Events").click()

	rows = panel.locator(".dt-log tbody tr")
	assert rows.count() == 2
	assert "submit" in rows.nth(0).inner_text() and "TodoList.add" in rows.nth(0).inner_text()
	assert "click" in rows.nth(1).inner_text() and "Counter.increment" in rows.nth(1).inner_text()
	assert "✓ matched" in rows.nth(1).inner_text()
	assert re.search(r"\d+(\.\d+)? ms", rows.nth(0).locator(".dt-server").inner_text())
	assert re.search(r"\d+ ms", rows.nth(0).locator(".dt-rtt").inner_text())

	submit, click = page.evaluate("Domino.devtools.log")
	assert submit["event"] == "submit" and submit["predicted"] is False and submit["status"] == 200
	assert click["event"] == "click" and click["predicted"] is True and click["matched"] is True
	for entry in (submit, click):
		assert entry["serverMs"] >= 0 and entry["roundTrip"] >= 0
		assert entry["sent"] > 0 and entry["received"] > 0
	assert submit["sent"] > click["sent"]  # the form's fields
	assert page.errors == []


def test_no_devtools_outside_debug(serve, page):

	page.goto(serve("devtools"))
	page.keyboard.press("Alt+Shift+D")

	assert page.evaluate("typeof Domino.inspect === 'undefined' && Domino.devtools === undefined")
	assert page.locator("#domino-inspector").count() == 0
	assert page.errors == []


def test_submit_marks_the_form_and_its_submit_button(serve, page):

	def slow(module):
		from components.todo_list import TodoList
		add = TodoList.add

		def delayed(self, event):
			time.sleep(0.5)
			return add(self, event)

		TodoList.add = delayed

	page.goto(serve("todo", slow))
	page.fill("input[name=text]", "one")
	page.press("input[name=text]", "Enter")

	page.wait_for_selector("form[data-loading][aria-busy=true]", timeout=2000)
	assert page.locator("button[type=submit]").is_disabled()
	assert page.locator("button[type=submit]").get_attribute("data-loading") == ""
	assert page.locator("input[name=text]").is_enabled()

	page.wait_for_function("document.querySelectorAll('li').length === 1", timeout=5000)
	assert page.locator("[data-loading]").count() == 0
	assert page.locator("button[type=submit]").is_enabled()
	assert page.errors == []


def test_latency_simulator_delays_round_trips(serve, page):

	# Without predictions, so the click shows only once the server answers
	def no_predictions(module):
		from components.counter import CounterComponent
		CounterComponent.optimistic = False

	page.goto(serve("counter", no_predictions))
	page.evaluate("Domino.enableLatencySim(600)")

	page.get_by_text("Increment").click()
	page.wait_for_timeout(300)
	assert "Current Count: 0" in page.locator("p").inner_text()

	page.wait_for_function("document.querySelector('p').textContent.includes('Current Count: 1')", timeout=3000)

	# Kept for the tab, so it survives a reload
	page.reload()
	assert page.evaluate("sessionStorage.getItem('domino-latency')") == "600"
	page.evaluate("Domino.disableLatencySim()")
	assert page.errors == []


def test_optimistic_update_shows_before_the_server_answers(serve, page):

	page.goto(serve("counter"))
	page.evaluate("Domino.enableLatencySim(1500)")

	page.get_by_text("Increment").click()
	# Well before the 1.5 s round trip: shown from the server's prediction
	page.wait_for_function("document.querySelector('p').textContent.includes('Current Count: 1')", timeout=700)
	assert page.evaluate("document.querySelector('.CounterComponent').hasAttribute('data-predicted')")

	page.wait_for_function("!document.querySelector('.CounterComponent').hasAttribute('data-predicted')", timeout=4000)
	assert "Current Count: 1" in page.locator("p").inner_text()
	page.evaluate("Domino.disableLatencySim()")
	assert page.errors == []


def test_wrong_prediction_is_corrected_by_the_server(serve, page):

	import sys

	page.goto(serve("counter"))
	module = sys.modules["example_counter"]
	(page_state,) = module.app.page_store.pages.values()
	(counter,) = page_state.components

	# A change the browser hasn't heard about (no push), so its prediction is out of date
	type(counter).count._of(counter)._value = 41

	page.evaluate("Domino.enableLatencySim(600)")
	page.get_by_text("Increment").click()
	page.wait_for_function("document.querySelector('p').textContent.includes('Current Count: 1')", timeout=500)

	page.wait_for_function("document.querySelector('p').textContent.includes('Current Count: 42')", timeout=4000)
	assert not page.evaluate("document.querySelector('.CounterComponent').hasAttribute('data-predicted')")
	page.evaluate("Domino.disableLatencySim()")
	assert page.errors == []


def instant_component(name):
	"""The instance of a component class of the instant example on its one open page."""

	module = sys.modules["example_instant"]
	(page_state,) = module.app.page_store.pages.values()

	return next(component for component in page_state.components if type(component).__name__ == name)


# Clicks a button (picked by a selector, and text if given) and reports what the component shows
# straight after, in the same task: before any answer from the server could have arrived
CLICK_AND_READ = """([button, text, shown]) => {
	const buttons = Array.from(document.querySelectorAll(button));
	const target = text ? buttons.find((el) => el.textContent.includes(text)) : buttons[0];
	const started = performance.now();
	target.click();
	return {
		shown: document.querySelector(shown).textContent.trim(),
		ms: performance.now() - started,
		loading: document.documentElement.hasAttribute('data-domino-loading'),
	};
}"""


def test_many_clicks_in_a_row_show_at_once_and_the_server_agrees(serve, page):

	sent = sent_events(page)
	page.goto(serve("instant"))
	page.evaluate("Domino.enableLatencySim(1500)")

	# Tabs: every click shows its tab at once, though no answer has come back yet
	started = time.monotonic()
	for tab in ["How", "Truth", "Overview", "Truth", "How"]:
		result = page.evaluate(CLICK_AND_READ, ["[role=tab]", tab, "[role=tabpanel]"])
		expected = {"Overview": "renders the states", "How": "follows those states", "Truth": "source of truth"}[tab]
		assert expected in result["shown"]
		assert result["ms"] < 100 and result["loading"]

	# Stepper: five clicks on +, each shown at once, then + is disabled at the top
	for value in range(1, 6):
		result = page.evaluate(CLICK_AND_READ, ["button[aria-label=More]", None, ".Stepper output"])
		assert result["shown"] == str(value)
		assert result["ms"] < 100
	assert page.locator("button[aria-label=More]").is_disabled()

	# The menu's options exist only while it's open: open, pick, open, pick
	page.evaluate(CLICK_AND_READ, [".SortMenu > button", None, ".SortMenu"])
	assert page.evaluate(CLICK_AND_READ, ["[role=menuitemradio]", "Oldest", ".SortMenu"])["shown"] == "Sort: Oldest ▾"
	page.evaluate(CLICK_AND_READ, [".SortMenu > button", None, ".SortMenu"])
	assert page.evaluate(CLICK_AND_READ, ["[role=menuitemradio]", "Most liked", ".SortMenu"])["shown"] == "Sort: Most liked ▾"

	# All of it before the first answer could arrive
	assert time.monotonic() - started < 1.4
	assert page.evaluate("document.querySelectorAll('[data-predicted]').length") == 3

	# The server got every event, in order, and ends up where the page already is
	page.wait_for_function("!document.querySelector('[data-predicted]')", timeout=10000)
	assert len(sent) == 14
	assert instant_component("Tabs").active == 1
	assert instant_component("Stepper").value == 5
	assert instant_component("SortMenu").choice == "Most liked" and instant_component("SortMenu").open is False
	assert "follows those states" in page.locator("[role=tabpanel]").inner_text()
	assert page.locator(".Stepper output").inner_text() == "5"
	assert page.locator(".SortMenu").inner_text().strip() == "Sort: Most liked ▾"
	page.evaluate("Domino.disableLatencySim()")
	assert page.errors == []


def test_clicks_keep_showing_at_once_after_the_server_answers(serve, page):

	page.goto(serve("instant"))
	page.evaluate("Domino.enableLatencySim(400)")

	page.get_by_label("Next").click()
	page.wait_for_function("!document.querySelector('[data-predicted]')", timeout=4000)
	assert page.locator("figure").inner_text() == "Noon (2/4)"

	# The answer brought the states from where the server is now
	result = page.evaluate(CLICK_AND_READ, ["button[aria-label=Next]", None, "figure"])
	assert result["shown"] == "Dusk (3/4)" and result["loading"]
	page.wait_for_function("!document.querySelector('[data-predicted]')", timeout=4000)
	assert instant_component("Carousel").index == 2
	page.evaluate("Domino.disableLatencySim()")
	assert page.errors == []


def test_the_server_corrects_states_that_turned_out_wrong(serve, page):

	page.goto(serve("instant"))
	stepper = instant_component("Stepper")

	# A change the browser hasn't heard about (no push), so the states it has are out of date
	type(stepper).value._of(stepper)._value = 3

	page.evaluate("Domino.enableLatencySim(600)")
	assert page.evaluate(CLICK_AND_READ, ["button[aria-label=More]", None, ".Stepper output"])["shown"] == "1"
	assert page.evaluate(CLICK_AND_READ, ["button[aria-label=More]", None, ".Stepper output"])["shown"] == "2"

	# The answer to the last click is what the server says: 3 + 2
	page.wait_for_function("document.querySelector('.Stepper output').textContent.trim() === '5'", timeout=4000)
	assert not page.evaluate("document.querySelector('.Stepper').hasAttribute('data-predicted')")
	assert page.locator("button[aria-label=More]").is_disabled()
	page.evaluate("Domino.disableLatencySim()")
	assert page.errors == []


def test_rapid_clicks_on_an_unbounded_counter_end_right_under_latency(serve, page):

	page.goto(serve("counter"))
	page.evaluate("Domino.enableLatencySim(500)")
	page.evaluate("() => { const button = document.querySelector('button'); for (let i = 0; i < 5; i++) button.click(); }")

	# The first click shows at once (one step ahead is all a counter gets)
	assert "Current Count: 1" in page.locator("p").inner_text()
	page.wait_for_function("document.querySelector('p').textContent.includes('Current Count: 5')", timeout=5000)
	page.wait_for_function("!document.querySelector('[data-predicted]')", timeout=5000)
	page.wait_for_timeout(300)
	assert "Current Count: 5" in page.locator("p").inner_text()
	page.evaluate("Domino.disableLatencySim()")
	assert page.errors == []


def test_a_failed_event_goes_back_to_what_the_server_showed(serve, page):

	def failing(module):
		# The page still has the states (the handler is predictable), but the server fails
		module.app.handle_event = lambda page, event_id, data: ({"error": "Internal Server Error"}, 500)

	page.goto(serve("instant", failing))
	page.evaluate("Domino.enableLatencySim(400)")
	page.evaluate("document.addEventListener('domino:error', (e) => e.preventDefault())")
	assert page.evaluate(CLICK_AND_READ, ["button[aria-label=More]", None, ".Stepper output"])["shown"] == "1"
	assert page.evaluate(CLICK_AND_READ, ["button[aria-label=More]", None, ".Stepper output"])["shown"] == "2"

	page.wait_for_function("!document.querySelector('[data-predicted]')", timeout=4000)
	assert page.locator(".Stepper output").inner_text() == "0"
	page.evaluate("Domino.disableLatencySim()")
	# Over HTTP the browser logs the 500s itself
	assert [error for error in page.errors if "status of 500" not in error] == []


@pytest.mark.mongo
def test_accounts_sign_up_log_out_log_in_and_keep_private_notes(serve, page):

	def configure(module):
		module.app.secret_key = "test"

	email = f"ada-{time.time_ns()}@example.com"
	home = serve("accounts", configure)
	page.goto(home)
	menu = page.locator(".UserMenu")

	menu.get_by_role("link", name="Sign up").click()
	page.fill("input[name=name]", "Ada")
	page.fill("input[name=email]", email)
	page.fill("input[name=password]", "correct horse")
	page.get_by_role("button", name="Sign up").click()

	# Back where the sign-up link was clicked, signed in
	page.wait_for_url(home)
	assert "Signed in as Ada" in menu.inner_text()

	menu.get_by_role("button", name="Log out").click()
	menu.get_by_role("link", name="Log in").wait_for()

	menu.get_by_role("link", name="Log in").click()
	page.fill("input[name=email]", email)
	page.fill("input[name=password]", "wrong password")
	page.get_by_role("button", name="Log in").click()
	page.get_by_role("alert").wait_for()
	assert page.get_by_role("alert").inner_text() == "Wrong email or password"
	assert page.input_value("input[name=email]") == email
	assert page.input_value("input[name=password]") == ""

	page.fill("input[name=password]", "correct horse")
	page.get_by_role("button", name="Log in").click()
	page.wait_for_url(home)
	assert "Signed in as Ada" in menu.inner_text()

	page.get_by_role("link", name="Private").click()
	page.wait_for_url(home + "private")
	page.fill("input[name=text]", "Buy milk")
	page.press("input[name=text]", "Enter")
	page.wait_for_function("document.querySelectorAll('.Notes li').length === 1", timeout=5000)
	assert page.locator(".Notes li").inner_text() == "Buy milk"
	assert page.errors == []


@pytest.mark.mongo
def test_accounts_forgot_password_email_and_reset(serve, page, mail_outbox):

	from domino import accounts

	def configure(module):
		module.app.secret_key = "test"

	accounts._mailed.clear()
	email = f"ada-{time.time_ns()}@example.com"
	home = serve("accounts", configure)
	menu = page.locator(".UserMenu")

	page.goto(home + "signup")
	page.fill("input[name=email]", email)
	page.fill("input[name=password]", "correct horse")
	page.get_by_role("button", name="Sign up").click()
	menu.get_by_role("button", name="Log out").click()
	menu.get_by_role("link", name="Log in").click()

	page.get_by_role("link", name="Forgot your password?").click()
	page.wait_for_url(home + "forgot-password")
	page.fill("input[name=email]", email)
	page.get_by_role("button", name="Email me a link").click()
	assert "we've emailed a link" in page.get_by_role("status").inner_text()

	# The server runs in this process, so its emails are in the outbox
	(message,) = [message for message in mail_outbox if message.subject == "Reset your password"]
	assert message.links[0].startswith(home + "reset-password?token=")
	page.goto(message.links[0])
	page.fill("input[name=password]", "a new password")
	page.fill("input[name=confirm]", "a different one")
	page.get_by_role("button", name="Change password").click()
	page.get_by_role("alert").wait_for()
	assert page.get_by_role("alert").inner_text() == "The passwords don't match"

	page.fill("input[name=password]", "a new password")
	page.fill("input[name=confirm]", "a new password")
	page.get_by_role("button", name="Change password").click()
	page.get_by_role("status").wait_for()
	assert page.get_by_role("status").inner_text().strip() == "Your password has been changed."

	page.locator("main").get_by_role("link", name="Log in").click()
	page.wait_for_url(home + "login")
	page.fill("input[name=email]", email)
	page.fill("input[name=password]", "a new password")
	page.get_by_role("button", name="Log in").click()
	page.locator(".LoginForm").get_by_text("Signed in as").wait_for()
	assert "Signed in as" in menu.inner_text()

	# The link was used up
	page.goto(message.links[0])
	assert page.locator("main [role=alert]").inner_text() == "This link is invalid or has expired."
	assert page.errors == []


def test_file_routed_pages_share_a_layout(serve, page):

	url = serve("functional")
	page.goto(url)

	page.get_by_role("link", name="About").click()
	page.wait_for_url("**/about")
	assert page.locator("h1").inner_text() == "About"
	assert page.locator("nav a[aria-current=page]").inner_text() == "About"

	page.get_by_role("link", name="Home").click()
	page.get_by_role("link", name="Grace").click()
	page.wait_for_url("**/hello/Grace")
	assert page.locator("h1").inner_text() == "Hello, Grace!"
	assert page.errors == []

	response = page.goto(url + "nowhere")
	assert response.status == 404
	assert page.locator("h1").inner_text() == "Page not found"
	assert page.locator("nav a").count() == 4


def test_component_css_from_an_event_response_is_added_once(page):

	import domino.tags as t
	from domino import Domino, State
	from domino.components import Document

	class Badge(t.span):

		css = {"color": "rgb(200, 0, 0)", "::after": {"content": "'!'"}}

	class Badges(t.div):

		shown = State(0)
		optimistic = False  # so Badge first shows up in an event response


		def render(self):

			return [t.button(on_click=self.more) ["More"]] + [Badge() [str(i)] for i in range(self.shown)]


		def more(self):

			self.shown += 1

	app = Domino(__name__)

	@app.route("/")
	def index():

		document = Document() [Badges()]
		document.style("span", font_weight="bold")
		return document

	server = make_server("127.0.0.1", 0, app, threaded=True)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	try:
		page.goto(f"http://127.0.0.1:{server.server_port}/")
		assert page.locator("style[data-domino-css]").count() == 0

		for count in (1, 2, 3):
			page.get_by_text("More").click()
			page.wait_for_function(f"document.querySelectorAll('.Badge').length === {count}")

		assert page.locator("style[data-domino-css~=Badge]").count() == 1
		# Before the page's own stylesheet, so the page's rules still win
		following = page.evaluate("document.querySelector('style[data-domino-css]').nextElementSibling.textContent")
		assert following.strip().startswith("span")
		assert page.evaluate("getComputedStyle(document.querySelector('.Badge')).color") == "rgb(200, 0, 0)"
		assert page.evaluate("getComputedStyle(document.querySelector('.Badge'), '::after').content") == '"!"'
		assert page.errors == []
	finally:
		server.shutdown()


def test_template_counter_is_instant(serve, page):

	page.goto(serve("templating"))
	page.evaluate("Domino.enableLatencySim(1000)")
	counter = page.locator(".Counter")

	counter.get_by_role("button", name="+1").click()
	# Predicted from the template, long before the server answers: Reset is enabled at once too
	page.wait_for_function("document.querySelector('.Counter strong').textContent === '1'", timeout=500)
	assert not counter.get_by_role("button", name="Reset").is_disabled()
	assert counter.locator(".hint").inner_text() == "Keep going."
	# A counter can go on forever, so only the next state is shipped; the server catches up
	counter.get_by_role("button", name="+1").click()
	page.wait_for_function("document.querySelector('.Counter strong').textContent === '2'", timeout=8000)
	page.wait_for_function("!document.querySelector('.Counter').hasAttribute('data-predicted')", timeout=8000)
	assert counter.locator("strong").inner_text() == "2"

	counter.get_by_role("button", name="Reset").click()
	page.wait_for_function("document.querySelector('.Counter strong').textContent === '0'", timeout=5000)
	page.wait_for_function("document.querySelector('.Counter button:nth-of-type(2)').disabled", timeout=5000)
	page.evaluate("Domino.disableLatencySim()")
	assert page.errors == []


def test_template_todo_list_adds_toggles_and_removes_each_item(serve, page):

	page.goto(serve("templating"))
	todos = page.locator(".Todos")

	todos.locator("input[name=text]").fill("Third <one>")
	todos.locator("input[name=text]").press("Enter")
	page.wait_for_function("document.querySelectorAll('.TodoList li').length === 3")
	assert todos.locator("li span").all_inner_texts() == ["Write the markup in HTML", "Keep the logic in Python", "Third <one>"]
	assert todos.locator("input[name=text]").input_value() == ""

	# Each item's checkbox and button have their own index
	todos.locator("li input[type=checkbox]").nth(1).click()
	page.wait_for_function("document.querySelector('.TodoList .hint').textContent === '1 left.'")
	assert "done" in todos.locator("li").nth(1).get_attribute("class")

	todos.locator("li .remove").nth(0).click()
	page.wait_for_function("document.querySelectorAll('.TodoList li').length === 2")
	assert todos.locator("li span").all_inner_texts() == ["Keep the logic in Python", "Third <one>"]

	for remaining in (1, 0):
		todos.locator("li .remove").first.click()
		page.wait_for_function(f"document.querySelectorAll('.TodoList li').length === {remaining}")
	page.wait_for_function("document.querySelector('.EmptyState')?.textContent === 'Nothing to do. Add something above!'")
	assert page.errors == []


def test_template_faq_toggles_instantly(serve, page):

	page.goto(serve("templating"))
	page.evaluate("Domino.enableLatencySim(1500)")
	faq = page.locator(".Faq")

	# on-click="toggle(index)": every state is shipped, so any number of clicks show at once
	faq.get_by_text("Where does the logic go?").click()
	page.wait_for_function("document.querySelectorAll('.Faq dd').length === 1", timeout=500)
	assert faq.locator("dd").inner_text().startswith("In Python")
	faq.get_by_text("Why is it instant?").click()
	page.wait_for_function("document.querySelector('.Faq dd').textContent.startsWith('toggle()')", timeout=500)
	faq.get_by_text("Why is it instant?").click()
	page.wait_for_function("document.querySelectorAll('.Faq dd').length === 0", timeout=500)
	assert faq.locator("button[aria-expanded=true]").count() == 0

	# The server agrees once it has answered every click
	page.wait_for_function("!document.querySelector('.Faq').hasAttribute('data-predicted')", timeout=10000)
	assert faq.locator("dd").count() == 0
	page.evaluate("Domino.disableLatencySim()")
	assert page.errors == []


def test_counter_in_a_jinja_page(serve, page):

	page.goto(serve("templating") + "jinja")
	page.evaluate("Domino.enableLatencySim(1000)")
	counter = page.locator(".Counter")

	counter.get_by_role("button", name="+1").click()
	# Predicted from the paired template, before the server answers
	page.wait_for_function("document.querySelector('.Counter strong').textContent.trim() === '1'", timeout=500)
	counter.get_by_role("button", name="+1").click()
	page.wait_for_function("document.querySelector('.Counter strong').textContent.trim() === '2'", timeout=5000)
	page.wait_for_function("!document.querySelector('.Counter').hasAttribute('data-predicted')", timeout=5000)

	counter.get_by_role("button", name="Reset").click()
	page.wait_for_function("document.querySelector('.Counter strong').textContent.trim() === '0'", timeout=5000)
	assert counter.get_by_role("button", name="Reset").is_disabled()
	page.evaluate("Domino.disableLatencySim()")
	assert page.errors == []


@pytest.mark.skipif(sys.version_info < (3, 14), reason="template strings need Python 3.14")
def test_template_string_todo(serve, page):

	page.goto(serve("templating") + "jinja")
	todo = page.locator(".Todo")

	for number, text in enumerate(["one", "two"], 1):
		todo.locator("input[name=text]").fill(text)
		todo.locator("input[name=text]").press("Enter")
		page.wait_for_function(f"document.querySelectorAll('.Todo li').length === {number}")

	assert todo.locator("p").inner_text() == "2 item(s)"
	todo.locator("li input[type=checkbox]").first.click()
	page.wait_for_function("document.querySelectorAll('.Todo li').length === 1")

	assert [text.strip() for text in todo.locator("li").all_inner_texts()] == ["two"]
	assert todo.locator("input[name=text]").input_value() == ""
	assert page.errors == []


def watch_transport(page):
	"""What the page opens to talk to the server: WebSockets, event POSTs and SSE streams."""

	seen = {"websockets": [], "posts": [], "streams": []}

	page.on("websocket", lambda ws: seen["websockets"].append(ws))
	page.on("request", lambda request: "/_domino/events" in request.url and seen["posts"].append(request))
	page.on("request", lambda request: "/_domino/stream" in request.url and seen["streams"].append(request))

	return seen


def test_asgi_events_go_over_one_websocket(serve_asgi, page):

	seen = watch_transport(page)
	page.goto(serve_asgi("counter"))

	for _ in range(3):
		page.get_by_text("Increment").click()
	page.wait_for_function("document.querySelector('p').textContent.includes('Current Count: 3')")

	assert len(seen["websockets"]) == 1
	# With the page id, for `domino serve`'s router
	assert "/_domino/ws?page=" in seen["websockets"][0].url
	assert seen["posts"] == [] and seen["streams"] == []
	assert page.errors == []


def test_asgi_pushes_go_over_the_websocket(serve_asgi, page):

	seen = watch_transport(page)
	updates = []
	page.on("websocket", lambda ws: ws.on("framereceived", lambda payload: '"update"' in payload and updates.append(payload)))
	page.goto(serve_asgi("clock"))
	first = page.locator("p").inner_text()

	page.wait_for_function(f"document.querySelector('p').textContent.trim() !== {first!r}", timeout=5000)
	assert updates
	assert len(seen["websockets"]) == 1
	assert seen["streams"] == []
	assert page.errors == []


def test_wsgi_pages_never_try_the_websocket(serve_wsgi, page):

	seen = watch_transport(page)
	page.goto(serve_wsgi("clock"))
	page.wait_for_timeout(1500)

	assert seen["websockets"] == []
	assert len(seen["streams"]) == 1


def test_falls_back_to_post_and_sse_when_the_websocket_is_blocked(serve_asgi, page):

	# Like a proxy that won't pass WebSockets: every socket closes before it opens
	page.add_init_script("""window.WebSocket = class {
		constructor() {
			window.socketsTried = (window.socketsTried || 0) + 1;
			setTimeout(() => this.onclose({ code: 1006 }), 10);
		}
		send() {}
		close() {}
	};""")
	seen = watch_transport(page)

	page.goto(serve_asgi("counter"))
	page.get_by_text("Increment").click()
	page.wait_for_function("document.querySelector('p').textContent.includes('Current Count: 1')", timeout=5000)
	assert len(seen["posts"]) == 1

	# A live page gives up on the socket after a few tries, then streams
	page.goto(serve_asgi("clock"))
	first = page.locator("p").inner_text()
	page.wait_for_function(f"document.querySelector('p').textContent.trim() !== {first!r}", timeout=8000)
	page.wait_for_timeout(3000)
	assert len(seen["streams"]) == 1
	# The first try and three retries, then no more
	assert page.evaluate("window.socketsTried") == 4
	assert page.errors == []


def test_live_page_reloads_when_its_socket_hears_it_expired(serve_asgi, page):

	def quick_keepalive(module):
		module.app.config["DOMINO_KEEPALIVE"] = 0.1

	page.goto(serve_asgi("clock", quick_keepalive))
	first = page.get_attribute("[data-domino-page]", "data-domino-page")

	# Gone from the server, e.g. after a restart
	sys.modules["example_clock"].app.page_store.delete(first)

	page.wait_for_function(f"document.querySelector('[data-domino-page]').dataset.dominoPage !== {first!r}", timeout=5000)
	assert page.errors == []


def watch_loads(page):
	"""Every document the page loads from scratch; pages swapped in by core.js are fetched instead."""

	documents = []
	page.on("request", lambda request: request.resource_type == "document" and request.frame == page.main_frame and documents.append(request.url))

	return documents


def mark(page):

	# Gone if the page is loaded from scratch; the <nav> is kept if swapped in
	page.evaluate("() => { window.__marker = 1; window.__nav = document.querySelector('nav'); window.__domino = window.Domino; }")


def kept(page):

	return page.evaluate("() => window.__marker === 1 && window.__nav === document.querySelector('nav')")


def test_links_swap_pages_in_without_reloading(serve, page):

	documents = watch_loads(page)
	url = serve("functional")
	page.goto(url)
	mark(page)

	page.get_by_role("link", name="About").click()
	page.wait_for_url("**/about")
	page.wait_for_function("document.querySelector('h1').textContent.trim() === 'About'")

	assert kept(page)
	assert page.title() == "About · My Website"
	assert page.locator("nav a[aria-current=page]").inner_text() == "About"
	# The new page's heading has focus, and its title is announced
	assert page.evaluate("document.activeElement.tagName") == "H1"
	page.wait_for_function("document.querySelector('[aria-live]').textContent.trim() === 'About · My Website'")
	assert page.evaluate("document.documentElement.hasAttribute('data-domino-loading')") is False

	page.get_by_role("link", name="Home").click()
	page.get_by_role("link", name="Grace").click()
	page.wait_for_function("document.querySelector('h1').textContent.trim() === 'Hello, Grace!'")
	assert page.url == url + "hello/Grace"
	assert kept(page)
	assert documents == [url]
	assert page.errors == []


def test_back_and_forward_swap_pages_too(serve, page):

	documents = watch_loads(page)
	url = serve("functional")
	page.goto(url)
	mark(page)

	page.get_by_role("link", name="About").click()
	page.wait_for_url("**/about")
	page.get_by_role("link", name="Contact").click()
	page.wait_for_url("**/contact")

	page.go_back()
	page.wait_for_function("document.querySelector('h1').textContent.trim() === 'About'")
	assert page.url == url + "about"
	page.go_back()
	page.wait_for_function("document.querySelector('h1').textContent.trim() === 'Welcome to My Website'")
	assert page.url == url
	page.go_forward()
	page.wait_for_function("document.querySelector('h1').textContent.trim() === 'About'")

	assert page.title() == "About · My Website"
	assert kept(page)
	assert documents == [url]
	assert page.errors == []


def test_events_work_on_a_page_swapped_in(serve, page):

	page.goto(serve("functional"))

	for _ in range(2):
		page.get_by_role("link", name="Counter").click()
		page.wait_for_function("document.querySelector('h1').textContent.trim() === 'Counter'")
		for _ in range(2):
			page.get_by_role("button", name="Click me").click()
		page.wait_for_function("document.querySelector('main p').textContent.includes('Clicked 2 times')", timeout=5000)
		page.get_by_role("link", name="About").click()
		page.wait_for_url("**/about")

	assert page.errors == []


def test_one_websocket_for_the_whole_visit(serve_asgi, page):

	seen = watch_transport(page)
	frames = []
	page.on("websocket", lambda ws: ws.on("framesent", lambda payload: frames.append(json.loads(payload)["type"])))
	page.goto(serve_asgi("functional"))

	# The home page needs nothing from the server; the counter opens the socket
	for _ in range(2):
		page.get_by_role("link", name="Counter").click()
		page.wait_for_function("document.querySelector('h1').textContent.trim() === 'Counter'")
		page.get_by_role("button", name="Click me").click()
		page.wait_for_function("document.querySelector('main p').textContent.includes('Clicked 1 times')", timeout=5000)
		page.get_by_role("link", name="About").click()
		page.wait_for_url("**/about")

	page.wait_for_function("document.querySelector('h1').textContent.trim() === 'About'")
	page.wait_for_timeout(100)
	assert len(seen["websockets"]) == 1
	assert seen["posts"] == [] and seen["streams"] == []
	assert frames == ["hello", "event", "leave", "hello", "event", "leave"]
	assert page.errors == []


def test_the_page_left_is_dropped_on_the_server(serve, page):

	url = serve("functional")
	app = sys.modules["example_functional"].app
	page.goto(url + "counter")
	page.get_by_role("button", name="Click me").click()
	page.wait_for_function("document.querySelector('main p').textContent.includes('Clicked 1 times')", timeout=5000)
	left = page.get_attribute("[data-domino-page]", "data-domino-page")
	assert left in app.page_store.pages

	page.get_by_role("link", name="Counter").click()
	page.wait_for_function(f"document.querySelector('[data-domino-page]').dataset.dominoPage !== {left!r}")
	shown = page.get_attribute("[data-domino-page]", "data-domino-page")

	deadline = time.monotonic() + 5
	while left in app.page_store.pages:
		assert time.monotonic() < deadline, "the page left is still kept"
		time.sleep(0.01)
	assert list(app.page_store.pages) == [shown]
	assert page.errors == []


@pytest.fixture
def site():
	"""A small app with a login_required page and a page that isn't Domino's."""

	from flask import Response

	import domino.tags as t
	from domino import Domino, accounts
	from domino.components import Document

	app = Domino(__name__)
	app.secret_key = "test"

	@app.route("/")
	def index():
		return Document(title="Home") [
			t.nav() [
				t.a(href="/private") ["Private"],
				t.a(href="/plain") ["Plain"],
				t.a(href="/login", data_domino_reload=True) ["Reload"],
				t.a(href="/login", target="_blank") ["New tab"],
				t.a(href="#bottom") ["Bottom"],
			],
			t.h1() ["Home"],
			t.p(style={"height": "3000px"}) ["Tall"],
			t.p(id="bottom") ["Bottom"],
		]

	@app.route("/private")
	@accounts.login_required
	def private():
		return Document(title="Private") [t.h1() ["Private"]]

	@app.route("/login")
	def login():
		return Document(title="Log in") [
			t.nav() [t.a(href="/") ["Home"]],
			t.h1() ["Log in"],
			t.script() ["window.ran = (window.ran || 0) + 1;"],
		]

	@app.route("/plain")
	def plain():
		return Response("<p>Not a Domino page</p>", mimetype="text/html")

	server = make_server("127.0.0.1", 0, app, threaded=True)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	yield f"http://127.0.0.1:{server.server_port}/"
	server.shutdown()


def test_redirects_within_the_site_end_at_the_final_url(site, page):

	documents = watch_loads(page)
	page.goto(site)
	mark(page)

	page.get_by_role("link", name="Private").click()
	page.wait_for_function("document.querySelector('h1').textContent.trim() === 'Log in'")

	assert page.url == site + "login?next=%2Fprivate"
	assert page.title() == "Log in"
	assert kept(page)
	assert documents == [site]
	# The new page's own script ran, once; Domino's didn't run again
	assert page.evaluate("window.ran") == 1
	assert page.evaluate("window.Domino === window.__domino")

	page.go_back()
	page.wait_for_function("document.querySelector('h1').textContent.trim() === 'Home'")
	assert page.url == site
	assert page.errors == []


def test_other_links_load_as_usual(site, page):

	documents = watch_loads(page)
	page.goto(site)
	mark(page)

	# A link to a place on the page only scrolls
	page.get_by_role("link", name="Bottom").click()
	page.wait_for_url("**/#bottom")
	assert page.evaluate("window.scrollY") > 1000
	assert kept(page)

	# Opening in a new tab, with a modifier key or target=_blank, leaves this page alone
	with page.context.expect_page() as opened:
		page.get_by_role("link", name="Private").click(modifiers=["Control"])
	opened.value.close()
	with page.context.expect_page() as opened:
		page.get_by_role("link", name="New tab").click()
	opened.value.close()
	assert page.url == site + "#bottom"
	assert kept(page)

	# Not a Domino page: loaded from scratch
	page.get_by_role("link", name="Plain").click()
	page.wait_for_function("document.body.textContent.includes('Not a Domino page')")
	assert page.evaluate("window.__marker") is None
	assert documents[-1] == site + "plain"

	# Opted out
	page.goto(site)
	mark(page)
	page.get_by_role("link", name="Reload").click()
	page.wait_for_function("document.querySelector('h1') && document.querySelector('h1').textContent.trim() === 'Log in'")
	assert page.evaluate("window.__marker") is None
	assert documents[-1] == site + "login"
	assert page.errors == []


def test_navigation_setting_off_loads_pages_as_usual(serve, page):

	def off(module):
		module.app.config["DOMINO_NAVIGATION"] = False

	documents = watch_loads(page)
	url = serve("functional", off)
	page.goto(url)
	mark(page)

	page.get_by_role("link", name="About").click()
	page.wait_for_url("**/about")
	page.wait_for_load_state()

	assert page.locator("h1").inner_text() == "About"
	assert page.evaluate("window.__marker") is None
	assert documents == [url, url + "about"]
	assert page.errors == []


def test_a_newer_navigation_cancels_the_one_in_flight(serve, page):

	documents = watch_loads(page)
	url = serve("functional")
	page.goto(url)
	page.evaluate("Domino.enableLatencySim(600)")

	page.get_by_role("link", name="About").click()
	page.wait_for_selector("html[data-domino-loading]")
	assert page.locator("nav a[aria-busy=true]").inner_text() == "About"
	page.get_by_role("link", name="Contact").click()
	page.wait_for_function("document.querySelector('h1').textContent.trim() === 'Contact'", timeout=5000)
	page.wait_for_timeout(700)

	assert page.url == url + "contact"
	assert page.locator("h1").inner_text() == "Contact"
	assert page.locator("[aria-busy]").count() == 0
	assert page.evaluate("document.documentElement.hasAttribute('data-domino-loading')") is False
	# Only Contact was added to the history
	page.go_back()
	page.wait_for_function("document.querySelector('h1').textContent.trim() === 'Welcome to My Website'", timeout=5000)
	page.evaluate("Domino.disableLatencySim()")
	assert documents == [url]
	assert page.errors == []


def png(width, height, color):
	"""A PNG image of one color, made without an image library."""

	def chunk(kind, data):
		return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

	rows = b"".join(b"\x00" + bytes(color) * width for _ in range(height))
	header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

	return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def image_file(name, color, size=64):

	return {"name": name, "mimeType": "image/png", "buffer": png(size, size, color)}


def test_uploads_show_thumbnails_and_clear_the_form(serve, page):

	uploads = []
	page.on("request", lambda request: "/_domino/upload" in request.url and uploads.append(request))
	page.goto(serve("uploads"))

	page.set_input_files("input[name=photos]", [image_file("red.png", (220, 40, 40)), image_file("blue.png", (40, 80, 220))])
	page.get_by_text("Upload", exact=True).click()
	page.wait_for_function("document.querySelectorAll('ul img').length === 2", timeout=5000)

	# Each thumbnail loads from the server
	page.wait_for_function("Array.from(document.querySelectorAll('ul img')).every((img) => img.complete && img.naturalWidth === 64)", timeout=5000)
	# The submitted form is reset, file input included
	assert page.evaluate("document.querySelector('input[name=photos]').files.length") == 0
	# One multipart POST, whichever transport carried the event
	assert len(uploads) == 1
	assert uploads[0].headers["x-domino-page"] == page.get_attribute("[data-domino-page]", "data-domino-page")

	# A file input's change event uploads as soon as a file is picked
	page.set_input_files("input[name=avatar]", [image_file("me.png", (40, 160, 80))])
	page.wait_for_function("document.querySelector('.avatar img') && document.querySelector('.avatar img').naturalWidth === 64", timeout=5000)
	assert page.errors == []


def test_upload_progress_is_marked_for_css(serve, page):

	page.goto(serve("uploads"))
	page.evaluate("Domino.enableLatencySim(1500)")

	page.set_input_files("input[name=photos]", [image_file("big.png", (200, 150, 0), 256)])
	page.get_by_text("Upload", exact=True).click()

	form = page.locator("form")
	page.wait_for_selector("form[data-uploading]", timeout=2000)
	assert form.get_attribute("aria-busy") == "true"
	progress = page.evaluate("getComputedStyle(document.querySelector('form')).getPropertyValue('--domino-upload-progress')")
	assert 0 <= float(progress) <= 1
	# The example's bar is the form's ::after, sized by the custom property
	assert page.evaluate("getComputedStyle(document.querySelector('form'), '::after').display") == "block"

	page.wait_for_function("document.querySelectorAll('ul img').length === 1", timeout=8000)
	assert form.get_attribute("data-uploading") is None
	assert form.get_attribute("style") is None
	page.evaluate("Domino.disableLatencySim()")
	assert page.errors == []


def test_too_large_upload_shows_an_error(serve, page):

	def small_limit(module):
		module.app.debug = True
		module.app.config["DOMINO_MAX_UPLOAD_MB"] = 0.05

	page.goto(serve("uploads", small_limit))

	# Random bytes, well over the 50 KB limit
	page.set_input_files("input[name=photos]", [{"name": "huge.png", "mimeType": "image/png", "buffer": os.urandom(300 * 1024)}])
	page.get_by_text("Upload", exact=True).click()

	overlay = page.locator("#domino-error")
	overlay.wait_for(timeout=5000)
	assert "Upload too large: the limit is 0.05 MB" in overlay.inner_text()
	assert page.locator("ul img").count() == 0
	assert page.locator("button[data-loading]").count() == 0
	assert [error for error in page.errors if "413" not in error and "Domino event error" not in error] == []


def test_a_page_swapped_in_shows_clicks_instantly(serve, page):

	# The new page's predicted states come with it, as on a page load
	page.goto(serve("functional"))
	page.get_by_role("link", name="Counter").click()
	page.wait_for_function("document.querySelector('h1').textContent.trim() === 'Counter'", timeout=5000)

	page.evaluate("Domino.enableLatencySim(1500)")
	# An unbounded count is predicted one step ahead
	page.get_by_text("Click me").click()
	# Well before the 1.5 s round trip
	page.wait_for_function("document.querySelector('main p').textContent.includes('Clicked 1 times')", timeout=700)

	page.wait_for_function("!document.querySelector('[data-predicted]')", timeout=8000)
	assert "Clicked 1 times" in page.inner_text("main p")
	page.evaluate("Domino.disableLatencySim()")
	assert page.errors == []


@pytest.fixture
def serve_workers(tmp_path):
	"""Serves an example with `domino serve --workers 2`: two processes behind the router."""

	started = []

	def start(name):
		served = Served(EXAMPLES / name, 2, tmp_path / f"{name}.log").start()
		started.append(served)
		return served.url

	yield start

	for served in started:
		served.stop()


def open_on_each_worker(browser, url, count=2):
	"""Tabs of `url`, one on each worker (page loads take turns, as do script requests)."""

	tabs = {}
	for _ in range(10):
		tab = browser.new_page()
		tab.errors = []
		tab.on("pageerror", lambda error, tab=tab: tab.errors.append(str(error)))
		tab.goto(url)
		worker = tab.get_attribute("[data-domino-page]", "data-domino-page").split("-")[0]
		if worker in tabs:
			tab.close()
		else:
			tabs[worker] = tab
		if len(tabs) == count:
			return list(tabs.values())

	raise AssertionError("pages didn't reach every worker")


def test_counter_through_serve_workers(serve_workers, browser):

	tabs = open_on_each_worker(browser, serve_workers("counter"))

	for clicks, tab in enumerate(tabs, 1):
		posts = []
		tab.on("request", lambda request, posts=posts: "/_domino/events" in request.url and posts.append(request))
		for _ in range(clicks * 2):
			tab.get_by_text("Increment").click()
		tab.wait_for_function(f"document.querySelector('p').textContent.includes('Current Count: {clicks * 2}')", timeout=5000)
		# Over the page's WebSocket, which the router passed to the page's worker
		assert posts == []

	for tab in tabs:
		assert tab.errors == []
		tab.close()


@pytest.mark.mongo
def test_chat_through_serve_workers_reaches_windows_on_the_other_worker(serve_workers, browser):

	import os

	import pymongo

	# The database the workers use (conftest sets it for the test run)
	with pymongo.MongoClient(os.environ["DOMINO_MONGO__URL"]) as client:
		client.get_default_database()["messages"].delete_many({})

	first, second = open_on_each_worker(browser, serve_workers("chat"))

	# Written by one worker, re-rendered on the other through MongoDB's change stream
	first.fill("input[name=name]", "Ada")
	first.fill("input[name=text]", "Hi from another process")
	first.press("input[name=text]", "Enter")
	second.wait_for_function("document.querySelectorAll('.messages li').length === 1", timeout=10000)
	assert "Hi from another process" in second.locator(".messages").inner_text()

	second.fill("input[name=name]", "Grace")
	second.fill("input[name=text]", "Hi back")
	second.press("input[name=text]", "Enter")
	first.wait_for_function("document.querySelectorAll('.messages li').length === 2", timeout=10000)

	for tab in (first, second):
		assert tab.errors == []
		tab.close()


def test_a_page_switch_to_another_worker_opens_a_socket_to_it(serve_asgi, page, monkeypatch):

	# Each page as if from another worker of `domino serve` (all served by one process here),
	# so every page switch moves to a page the open socket's worker doesn't have
	import itertools
	import domino.core
	workers = itertools.cycle(["w1-", "w2-", "w3-"])
	monkeypatch.setattr(domino.core, "worker_prefix", lambda: next(workers))

	sockets = []
	posts = []
	page.on("websocket", lambda ws: sockets.append(ws))
	page.on("request", lambda request: "/_domino/events" in request.url and posts.append(request))
	page.goto(serve_asgi("functional") + "counter")
	page.get_by_text("Click me").click()
	page.wait_for_function("document.querySelector('main p').textContent.includes('Clicked 1 times')", timeout=5000)

	page.get_by_role("link", name="Home").click()
	page.wait_for_function("document.querySelector('h1').textContent.includes('Welcome')", timeout=5000)
	page.get_by_role("link", name="Counter").click()
	page.wait_for_function("document.querySelector('h1').textContent.trim() === 'Counter'", timeout=5000)
	page.get_by_text("Click me").click()
	page.get_by_text("Click me").click()
	page.wait_for_function("document.querySelector('main p').textContent.includes('Clicked 2 times')", timeout=5000)

	# The second counter (w3) is on another worker than the socket (w1): a new socket, the old
	# one closed once its events were answered; no POSTs
	assert [ws.url.split("page=")[1][:3] for ws in sockets] == ["w1-", "w3-"]
	page.wait_for_timeout(300)
	assert [ws.is_closed() for ws in sockets] == [True, False]
	assert posts == []
	assert page.errors == []


def test_uploads_through_serve_workers_reach_the_page_worker(serve_workers, browser):

	tabs = open_on_each_worker(browser, serve_workers("uploads"))

	for tab in tabs:
		tab.set_input_files("input[name=photos]", [image_file("red.png", (220, 40, 40))])
		tab.get_by_text("Upload", exact=True).click()
		# The upload and its event went to the worker with this tab's page
		tab.wait_for_function("document.querySelectorAll('ul img').length === 1", timeout=5000)
		assert tab.errors == []
		tab.close()


# Patches (a component sent as what changed) and hidden tabs (see domino/patches.py)


@pytest.fixture(params=["wsgi", "asgi"])
def serve_app(request, asgi_server):
	"""Serves an app made in the test on both transports."""

	servers = []

	def start(app):
		if request.param == "asgi":
			return asgi_server(app).url
		server = make_server("127.0.0.1", 0, app, threaded=True)
		threading.Thread(target=server.serve_forever, daemon=True).start()
		servers.append(server)
		return f"http://127.0.0.1:{server.server_port}/"

	start.transport = request.param
	yield start

	for server in servers:
		server.shutdown()


def received_frames(page):
	"""Messages the page's WebSocket receives, parsed."""

	frames = []
	page.on("websocket", lambda ws: ws.on("framereceived", lambda payload: frames.append(json.loads(payload))))

	return frames


# The DOM of an element as a page load would build it: tags, sorted attributes, checked, and
# text without the whitespace around it (updates are indented differently from the page)
CANONICAL_DOM = """(selector) => {
    const walk = (node) => {
        if (node.nodeType === Node.TEXT_NODE) return node.nodeValue.trim();
        if (node.nodeType !== Node.ELEMENT_NODE) return '';
        const attributes = Array.from(node.attributes).map((a) => a.name + '=' + a.value).sort().join(' ');
        const children = Array.from(node.childNodes).map(walk).filter(Boolean).join('');
        return '<' + node.tagName + ' ' + attributes + ' checked:' + !!node.checked + '>' + children + '</' + node.tagName + '>';
    };
    return walk(document.querySelector(selector));
}"""


def test_a_long_list_edited_many_times_ends_like_a_fresh_load(serve_app, browser):

	import random

	import domino.tags as t
	from domino import Collection, Domino
	from domino.components import Document

	items = Collection()
	for number in range(100):
		items.insert({"_id": f"i{number:03}", "text": f"Item {number}, something to do", "done": False, "order": number})

	class Todos(t.div):

		def render(self):
			documents = items.find(sort="order").fetch()
			return [
				t.button(id="add", on_click=self.add) ["Add"],
				t.ul()([
					t.li(id=item["_id"], class_="done" if item["done"] else None) [
						t.input(type="checkbox", checked=item["done"], on_change=lambda event, key=item["_id"]: self.toggle(key)),
						t.span() [item["text"]],
						t.button(class_="rename", on_click=lambda event, key=item["_id"]: self.rename(key)) ["Rename"],
						t.button(class_="remove", on_click=lambda event, key=item["_id"]: self.remove(key)) ["Remove"],
					]
					for item in documents
				]),
				t.p(id="count") [f"{len(documents)} items, {sum(item['done'] for item in documents)} done"]
			]

		def add(self):
			first = items.find(sort="order", limit=1).fetch()
			items.insert({"text": "Added at the top", "done": False, "order": first[0]["order"] - 1 if first else 0})

		def toggle(self, key):
			item = items.find_one({"_id": key})
			items.update({"_id": key}, {"$set": {"done": not item["done"]}})

		def rename(self, key):
			items.update({"_id": key}, {"$set": {"text": items.find_one({"_id": key})["text"] + " (renamed é 😀)"}})

		def remove(self, key):
			items.remove({"_id": key})

	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document() [Todos(id="todos")]

	url = serve_app(app)
	page = browser.new_page()
	frames = received_frames(page)
	errors = []
	page.on("pageerror", lambda error: errors.append(str(error)))
	try:
		page.goto(url)
		rng = random.Random(7)
		for _ in range(40):
			action = rng.choice(["toggle", "rename", "rename", "remove", "add"])
			length = page.evaluate("document.querySelector('#todos').outerHTML.length")
			if action == "add":
				page.click("#add")
			else:
				row = page.locator("li").nth(rng.randrange(page.locator("li").count()))
				row.locator({"toggle": "input", "rename": ".rename", "remove": ".remove"}[action]).click()
			# Each action changes the HTML; wait for it before the next
			page.wait_for_function(f"document.querySelector('#todos').outerHTML.length !== {length}", timeout=5000)

		page.wait_for_function("!document.documentElement.hasAttribute('data-domino-loading')")
		edited = page.evaluate(CANONICAL_DOM, "#todos")

		fresh = browser.new_page()
		fresh.goto(url)
		assert fresh.evaluate(CANONICAL_DOM, "#todos") == edited
		fresh.close()

		if serve_app.transport == "asgi":
			assert sum("patch" in frame for frame in frames) >= 30
		assert errors == []
	finally:
		page.close()


def chat_app():

	import domino.tags as t
	from domino import Collection, Domino
	from domino.components import Document

	messages = Collection()
	for number in range(200):
		messages.insert({"text": f"Message {number}", "sent": number})

	class Chat(t.div):

		def render(self):
			return [
				t.ul()([t.li() [message["text"]] for message in messages.find(sort="sent")]),
				t.form(on_submit=self.send) [
					t.input(name="text"),
					t.button(type="submit") ["Send"]
				]
			]

		def send(self, event):
			messages.insert({"text": event.form["text"], "sent": len(messages.find().fetch())})

	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document() [Chat()]

	return app


def send_message(page, text):

	page.fill("input[name=text]", text)
	page.press("input[name=text]", "Enter")


def test_chat_appends_reach_other_windows(serve_app, browser):

	url = serve_app(chat_app())
	reader, writer = browser.new_page(), browser.new_page()
	frames = received_frames(reader)
	try:
		reader.goto(url)
		writer.goto(url)
		for number in range(1, 6):
			send_message(writer, f"Hello {number}")
			reader.wait_for_function(f"document.querySelectorAll('li').length === {200 + number}", timeout=5000)

		assert reader.locator("li").last.inner_text() == "Hello 5"
		assert reader.locator("li").first.inner_text() == "Message 0"
		if serve_app.transport == "asgi":
			updates = [frame for frame in frames if frame.get("type") == "update"]
			# The first is whole; after it, a line or two each
			assert all("patch" in update for update in updates[1:])
			assert all(len(json.dumps(update)) < 300 for update in updates[1:])
	finally:
		reader.close()
		writer.close()


HIDE = """(hidden) => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => hidden ? 'hidden' : 'visible' });
    document.dispatchEvent(new Event('visibilitychange'));
}"""


def test_a_hidden_tab_gets_one_update_when_shown(serve_app, browser):

	url = serve_app(chat_app())
	hidden, writer = browser.new_page(), browser.new_page()
	frames = received_frames(hidden)
	try:
		hidden.goto(url)
		writer.goto(url)
		hidden.wait_for_function("!document.documentElement.hasAttribute('data-domino-loading')")
		hidden.evaluate(HIDE, True)
		time.sleep(0.3)

		for number in range(1, 4):
			send_message(writer, f"While hidden {number}")
			writer.wait_for_function(f"document.querySelectorAll('li').length === {200 + number}", timeout=5000)
		time.sleep(0.5)

		if serve_app.transport == "asgi":
			# Paused: the server sent it nothing, and its page still shows what it had
			assert [frame for frame in frames if frame.get("type") == "update"] == []
			assert hidden.locator("li").count() == 200

		hidden.evaluate(HIDE, False)
		hidden.wait_for_function("document.querySelectorAll('li').length === 203", timeout=5000)
		assert hidden.locator("li").last.inner_text() == "While hidden 3"

		if serve_app.transport == "asgi":
			time.sleep(0.3)
			assert len([frame for frame in frames if frame.get("type") == "update"]) == 1

		# And it's live again
		send_message(writer, "Shown")
		hidden.wait_for_function("document.querySelectorAll('li').length === 204", timeout=5000)
	finally:
		hidden.close()
		writer.close()


def test_large_predicted_states_arrive_as_patches_and_show_at_once(serve_app, page):

	import domino.tags as t
	from domino import Domino, State
	from domino.components import Document

	class Picker(t.div):

		picked = State(0)

		def render(self):
			return [
				t.ul()([
					t.li(class_="picked" if number == self.picked else None) [
						t.button(on_click=lambda event, number=number: self.pick(number)) [
							f"Option {number}, with a description long enough to matter"
						]
					]
					for number in range(30)
				])
			]

		def pick(self, number):
			self.picked = number

	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document() [Picker()]

	page.goto(serve_app(app))
	assert '"base":' in page.content()
	page.evaluate("Domino.enableLatencySim(1500)")

	for number in (3, 5):
		page.get_by_text(f"Option {number},").click()
		# Well before the 1.5 s round trip: shown from a predicted state sent as a patch
		page.wait_for_function(f"document.querySelector('li.picked').textContent.includes('Option {number},')", timeout=700)
		page.wait_for_function("!document.querySelector('[data-predicted]')", timeout=8000)

	assert page.locator("li.picked").count() == 1
	page.evaluate("Domino.disableLatencySim()")
	assert page.errors == []


@pytest.mark.parametrize("transport", ["wsgi", "asgi"])
def test_tailwind_rebuilds_are_swapped_in_without_reloading(transport, page, tmp_path, monkeypatch, asgi_server):

	import domino.tags as t
	from domino import Domino, tailwind
	from domino.components import Document
	from test_tailwind import write_fake_cli

	monkeypatch.setenv("DOMINO_HOME", str(tmp_path / "home"))
	monkeypatch.setenv(tailwind.ENV_BIN, str(write_fake_cli(tmp_path)))
	folder = tmp_path / "app"
	folder.mkdir()
	(folder / "settings.json").write_text('{"tailwind": true}')
	(folder / "page.py").write_text('shown = "tw-red"')

	app = Domino(__name__, root_path=str(folder), pages=False)
	app.debug = True

	@app.route("/")
	def index():

		# The second class isn't written out anywhere yet, so the CLI doesn't build it
		return Document() [
			t.p(id="a", class_="tw-red") ["built"],
			t.p(id="b", class_="tw-" + "later") ["not yet"]
		]

	tailwind.watch(folder, app.tailwind)
	opened = []
	page.on("websocket", lambda ws: "/_domino/tailwind/watch" in ws.url and opened.append("websocket"))
	page.on("request", lambda request: "/_domino/tailwind/watch" in request.url and opened.append("stream"))

	if transport == "wsgi":
		server = make_server("127.0.0.1", 0, app, threaded=True)
		threading.Thread(target=server.serve_forever, daemon=True).start()
		url = f"http://127.0.0.1:{server.server_port}/"
	else:
		url = asgi_server(app).url

	color = "(selector) => getComputedStyle(document.querySelector(selector)).color"
	try:
		page.goto(url)
		page.evaluate("window.notReloaded = true")
		assert page.evaluate(color, "#a") == "rgb(255, 0, 0)"
		assert page.evaluate(color, "#b") != "rgb(255, 0, 0)"
		before = page.get_attribute("link[data-domino-tailwind]", "href")

		# Writing the class out somewhere (here a template) rebuilds the CSS, and the page swaps it in
		(folder / "later.html").write_text('<p class="tw-later"></p>')
		page.wait_for_function("getComputedStyle(document.querySelector('#b')).color === 'rgb(255, 0, 0)'", timeout=10000)

		assert page.evaluate("window.notReloaded") is True
		assert page.locator("link[data-domino-tailwind]").count() == 1
		assert page.get_attribute("link[data-domino-tailwind]", "href") != before
		# Its own socket over ASGI (the server closes it at once when restarting), else a stream
		assert opened[0] == ("websocket" if transport == "asgi" else "stream")
		assert page.errors == []
	finally:
		page.close()
		if transport == "wsgi":
			server.shutdown()
		tailwind.stop_all()
