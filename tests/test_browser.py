"""End-to-end tests of core.js in a real browser. Skipped when Playwright isn't installed."""

import importlib.util
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
		spec = importlib.util.spec_from_file_location(f"example_{name}", EXAMPLES / f"{name}.py")
		module = importlib.util.module_from_spec(spec)
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
	# The other window can get the push before this one has applied its own response
	first.wait_for_function("document.querySelector('input[name=text]').value === ''", timeout=5000)

	assert second.input_value("input[name=text]") == "half-typed"
	assert first.input_value("input[name=name]") == "Ada"
	assert first.input_value("input[name=text]") == ""
	assert errors == []

	for window in windows:
		window.close()

