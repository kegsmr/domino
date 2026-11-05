"""Client components in a real browser: examples/client with the runtime served from the local copy
(downloaded once from npm into ~/.domino/client-runtime). Skipped when Playwright isn't installed
or the runtime can't be downloaded."""

import re
import time

import pytest

playwright = pytest.importorskip("playwright.sync_api")

from domino import _client as client


def runtime_or_skip(name):

	try:
		return client.ensure_runtime(name)
	except Exception as error:
		pytest.skip(f"the {name} runtime couldn't be installed: {error}")


@pytest.fixture(scope="module")
def browser():

	with playwright.sync_playwright() as p:
		browser = p.chromium.launch()
		yield browser
		browser.close()


@pytest.fixture
def page(browser):

	page = browser.new_page()
	page.errors = []
	page.on("console", lambda message: message.type == "error" and page.errors.append(message.text))
	page.on("pageerror", lambda error: page.errors.append(str(error)))
	yield page
	page.close()


@pytest.fixture
def serve(asgi_server, load_example):
	"""Serves examples/client with uvicorn, the runtime from the local copy."""

	def start(python="micropython"):
		runtime_or_skip(python)
		app = load_example("client").app
		app.config["DOMINO_CLIENT_RUNTIME"] = "local"
		app.config["DOMINO_CLIENT_PYTHON"] = python
		return asgi_server(app)

	return start


def hydrate(page, server, timeout=30000):

	page.goto(server.url)
	page.wait_for_selector(".Life[data-domino-hydrated]", timeout=timeout)
	page.wait_for_selector(".TextStats[data-domino-hydrated]", timeout=timeout)


def generation(page):

	return int(re.search(r"Generation (\d+)", page.text_content(".Life .status")).group(1))


def test_the_page_works_before_python_loads(serve, page):

	server = serve()
	# The runtime never arrives
	page.route("**/_domino/client/runtime/**", lambda route: route.abort())
	page.goto(server.url)

	# What the server rendered
	assert page.locator(".Life .board span").count() == 400
	assert page.text_content(".Life .status") == "Generation 0 · 16 alive"
	page.wait_for_timeout(500)
	assert page.locator("[data-domino-hydrated]").count() == 0

	# Server components still work
	page.fill(".ServerTextStats textarea", "Just the server.")
	page.wait_for_function("document.querySelector('.ServerTextStats dd').textContent.trim() === '16'")


def test_it_runs_in_the_browser_and_keeps_going_offline(serve, page):

	server = serve()
	hydrate(page, server)
	assert page.evaluate("Domino.client.python") == "micropython"
	assert page.errors == []

	# Cut the server off: no more requests, and the server itself stops
	page.route("**/*", lambda route: route.abort())
	server.stop()

	# A click on a cell, at once
	cell = page.locator(".Life .board span").nth(0)
	assert cell.get_attribute("class") is None
	cell.click()
	assert cell.get_attribute("class") == "on"
	assert page.text_content(".Life .status") == "Generation 0 · 17 alive"

	# Generations tick in the browser, many a second
	page.click(".Life button:has-text('Start')")
	start = time.monotonic()
	page.wait_for_function("/Generation ([2-9]\\d|\\d{3,})/.test(document.querySelector('.Life .status').textContent)", timeout=15000)
	assert time.monotonic() - start < 15
	page.click(".Life button:has-text('Pause')")
	paused = generation(page)
	page.wait_for_timeout(300)
	assert generation(page) == paused

	# Every keystroke counted in the browser
	page.fill(".TextStats:not(.ServerTextStats) textarea", "Offline, still counting. Yes!")
	page.wait_for_function("document.querySelector('.TextStats:not(.ServerTextStats) dd').textContent.trim() === '29'")
	assert "Words 4" in " ".join(page.locator(".TextStats:not(.ServerTextStats) dl").inner_text().split())

	# The server's copy of the same component can't answer now
	before = page.text_content(".ServerTextStats dl")
	page.fill(".ServerTextStats textarea", "Anyone there?")
	page.wait_for_timeout(500)
	assert page.text_content(".ServerTextStats dl") == before


def test_emit_reaches_the_server_and_the_board_keeps_running(serve, page):

	server = serve()
	hydrate(page, server)

	page.click(".Life button:has-text('Step')")
	page.click(".Life button:has-text('Step')")
	page.click(".Life .board span >> nth=0")
	alive = int(re.search(r"(\d+) alive", page.text_content(".Life .status")).group(1))
	page.click(".Life button.save")

	page.wait_for_selector(".Patterns li")
	assert page.text_content(".Patterns li").strip() == f"Generation 2: {alive} cells alive"

	# The server re-rendered Patterns, around the board, which kept its state
	assert generation(page) == 2
	assert page.locator(".Life[data-domino-hydrated]").count() == 1

	page.click(".Life button:has-text('Step')")
	assert generation(page) == 3
	assert page.errors == []


def test_errors_in_handlers_are_reported(serve, page):

	server = serve()
	hydrate(page, server)
	page.evaluate("""() => {
		document.addEventListener('domino:error', (e) => { window.reported = e.detail; e.preventDefault(); });
	}""")
	assert page.evaluate("Domino.client.islands.size") == 2

	# A handler the Python side doesn't have
	page.evaluate("document.querySelector('.Life .status').dataset.dominoOn = 'click:999'")
	page.click(".Life .status")
	page.wait_for_function("window.reported")

	assert page.evaluate("window.reported.error").startswith("IndexError")
	assert "dispatch" in page.evaluate("window.reported.traceback")


def test_the_same_code_runs_on_pyodide(serve, page):

	server = serve("pyodide")
	hydrate(page, server, timeout=120000)
	assert page.evaluate("Domino.client.python") == "pyodide"

	page.click(".Life button:has-text('Step')")
	assert generation(page) == 1
	page.fill(".TextStats:not(.ServerTextStats) textarea", "Full CPython.")
	page.wait_for_function("document.querySelector('.TextStats:not(.ServerTextStats) dd').textContent.trim() === '13'")
	assert page.errors == []
