"""End-to-end tests of core.js in a real browser. Skipped when Playwright isn't installed."""

import json
import sys
import threading
import time

import pytest

playwright = pytest.importorskip("playwright.sync_api")

from werkzeug.serving import make_server


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
	assert "Traceback" in overlay.locator("pre").inner_text()
	assert any("Domino event error" in error for error in page.errors)
	assert unexpected(page.errors) == []

	# The button works again, and the overlay can be closed
	assert page.get_by_text("Raise an exception").is_enabled()
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
	assert page.locator("nav a").count() == 3


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


def test_counter_paired_with_a_jinja_template_in_a_jinja_page(serve, page):

	page.goto(serve("templating"))
	page.evaluate("Domino.enableLatencySim(1000)")
	counter = page.locator(".Counter")

	counter.get_by_text("+1").click()
	# Predicted from the paired template, before the server answers
	page.wait_for_function("document.querySelector('.Counter strong').textContent === '1'", timeout=500)
	counter.get_by_text("+1").click()
	page.wait_for_function("document.querySelector('.Counter strong').textContent === '2'", timeout=5000)
	page.wait_for_function("!document.querySelector('.Counter').hasAttribute('data-predicted')", timeout=5000)

	counter.get_by_text("Reset").click()
	page.wait_for_function("document.querySelector('.Counter strong').textContent === '0'", timeout=5000)
	assert counter.get_by_text("Reset").is_disabled()
	page.evaluate("Domino.disableLatencySim()")
	assert page.errors == []


@pytest.mark.skipif(sys.version_info < (3, 14), reason="template strings need Python 3.14")
def test_template_string_todo(serve, page):

	page.goto(serve("templating"))
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
	assert seen["websockets"][0].url.endswith("/_domino/ws")
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
