"""End-to-end tests of core.js in a real browser. Skipped when Playwright isn't installed."""

import importlib.util
import sys
import threading
import time
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")

from werkzeug.serving import make_server


EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture(scope="module")
def browser():

	with playwright.sync_playwright() as p:
		browser = p.chromium.launch()
		yield browser
		browser.close()


@pytest.fixture
def serve():

	servers = []

	def start(name, patch=None):
		# Examples with their own folder keep their app in <name>/app.py
		path = EXAMPLES / f"{name}.py"
		if not path.exists():
			path = EXAMPLES / name / "app.py"
		spec = importlib.util.spec_from_file_location(f"example_{name}", path)
		module = importlib.util.module_from_spec(spec)
		# Flask finds the app's folder (for settings.json) through sys.modules
		sys.modules[spec.name] = module
		spec.loader.exec_module(module)
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


def test_debounced_search_keeps_focus_and_typing(serve, page):

	def slow(module):
		search = module.Search.search

		def delayed(self, event):
			time.sleep(0.3)
			return search(self, event)

		module.Search.search = delayed

	posts = []
	page.on("request", lambda request: request.method == "POST" and posts.append(request))
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
	assert len(posts) == 2
	assert page.errors == []


def test_server_push_updates_the_clock_without_user_action(serve, page):

	page.goto(serve("clock"))
	first = page.locator("p").inner_text()

	page.wait_for_function(f"document.querySelector('p').textContent.trim() !== {first!r}", timeout=5000)
	assert page.errors == []


@pytest.mark.mongo
def test_reactive_chat_updates_other_windows_and_keeps_their_typing(serve, browser):

	url = serve("chat")
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


def test_already_disabled_buttons_stay_disabled(serve, page):

	# A response that updates nothing, so only the busy marks touch the button
	page.goto(serve("counter"))
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
		search = module.Search.search

		def delayed(self, event):
			time.sleep(0.5)
			return search(self, event)

		module.Search.search = delayed

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
		add = module.TodoList.add

		def delayed(self, event):
			time.sleep(0.5)
			return add(self, event)

		module.TodoList.add = delayed

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
