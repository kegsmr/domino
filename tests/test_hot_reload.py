"""Hot reloading (domino.hot): changed files are swapped into the running app and open pages are
updated in place, keeping their components' State; what can't be swapped restarts the server."""

import os
import re
import subprocess
import sys
import textwrap
import time

import pytest

import domino.asgi
import domino.cli as cli
from domino import hot
from domino.hot import HotReloader, restart_only

from conftest import ROOT, wait_until


APP = '''\
from domino import Domino

app = Domino(__name__)
'''

COUNTER = '''\
import domino.tags as t
from domino import State


class Counter(t.div):

	count = State(0)


	def render(self):

		return [
			t.p() [f"Count: {self.count}"],
			t.button(on_click=self.increment) ["+"],
		]


	def increment(self):

		self.count += 1
'''

INDEX = '''\
import domino.tags as t
from domino.components import Document

from components.counter import Counter


def page():

	return Document(title="Hot") [
		t.h1() ["Counter"],
		Counter()
	]
'''


def dedent(text):

	return textwrap.dedent(text).replace("    ", "\t")


@pytest.fixture
def make_app(tmp_path, forget_modules):
	"""make_app({path: text}) writes an app folder (with app.py, components/counter.py and
	pages/index.py unless given) and loads it with a HotReloader whose restarts are recorded."""

	folders = []

	def make(files=None, name="app"):

		folder = tmp_path / name
		files = dict({"app.py": APP, "components/counter.py": COUNTER, "pages/index.py": INDEX}, **(files or {}))
		for path, text in files.items():
			write(folder / path, text)
		folders.append(folder)

		app = cli.find_app(cli.load_module(folder / "app.py"))
		app.debug = True
		reloader = HotReloader(app, folder / "app.py")
		reloader.restarts = []
		reloader.restart = reloader.restarts.append
		reloader.folder = folder

		return app, reloader

	yield make

	for folder in folders:
		forget_modules(folder)


def write(path, text):

	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(text, encoding="utf-8")


def change(reloader, path, text):
	"""Save `path` (in the app's folder) with `text` and let the reloader handle it."""

	path = reloader.folder / path
	write(path, text)

	return reloader.reload([str(path)])


def messages(app, page):
	"""The messages pushed to a test page's page since it last synced, taking them."""

	stored = app.page_store.load(page.page_id)
	with stored.updates_ready:
		found = list(stored.updates.values())
		stored.updates.clear()

	return found


def test_component_change_updates_the_page_and_keeps_its_state(make_app):

	app, reloader = make_app()
	page = app.test_page("/")
	page.click("button", text="+")
	page.click("button", text="+")
	assert page.text("p") == "Count: 2"

	assert change(reloader, "components/counter.py", COUNTER.replace("Count:", "Total:")) == "hot"

	# Only the component is sent again, and its state is the same
	(update, hot_message) = messages(app, page)
	assert "Total: 2" in update["html"]
	assert hot_message == {"type": "hot"}
	page.apply(update, None)
	assert page.text("p") == "Total: 2"
	assert page.text("h1") == "Counter"

	# Its handlers are the new ones
	change(reloader, "components/counter.py", COUNTER.replace("Count:", "Total:").replace("self.count += 1", "self.count += 10"))
	page.sync()
	page.click("button", text="+")
	assert page.text("p") == "Total: 12"

	# New pages get the new code too
	assert app.test_page("/").text("p") == "Total: 0"


def test_new_state_attributes_start_at_their_default_and_old_ones_keep_their_values(make_app):

	app, reloader = make_app()
	page = app.test_page("/")
	page.click("button", text="+")

	added = COUNTER.replace("count = State(0)", "count = State(0)\n\tlabel = State('Clicks')").replace('f"Count: {self.count}"', 'f"{self.label}: {self.count}"')
	change(reloader, "components/counter.py", added)
	page.sync()
	assert page.text("p") == "Clicks: 1"

	# A State that's gone is dropped from the component
	removed = added.replace("\tcount = State(0)\n", "").replace("{self.count}", "-").replace("self.count += 1", "pass")
	change(reloader, "components/counter.py", removed)
	page.sync()
	assert page.text("p") == "Clicks: -"
	counter = app.page_store.load(page.page_id).hot.root.body.__children__[1]
	assert "__state_label__" in vars(counter) and "__state_count__" not in vars(counter)


def test_page_module_change_updates_open_pages_and_its_route(make_app):

	app, reloader = make_app()
	page = app.test_page("/")
	page.click("button", text="+")

	assert change(reloader, "pages/index.py", INDEX.replace('["Counter"]', '["Hot counter"]')) == "hot"

	# The page is made again by its view, and the counter in the same place keeps its count
	(message,) = messages(app, page)
	assert message["type"] == "hot" and message["error"] is None
	page.apply(message, None)
	assert page.text("h1") == "Hot counter"
	assert page.text("p") == "Count: 1"
	page.click("button", text="+")
	assert page.text("p") == "Count: 2"

	# and its route serves the new page
	assert app.test_page("/").text("h1") == "Hot counter"


def test_new_and_deleted_pages(make_app):

	app, reloader = make_app()
	client = app.test_client()
	assert client.get("/about").status_code == 404
	client.get("/")

	about = "import domino.tags as t\n\n\ndef page():\n\n\treturn t.p() [\"About us\"]\n"
	assert change(reloader, "pages/about.py", about) == "hot"
	response = client.get("/about")
	assert response.status_code == 200 and "About us" in response.get_data(as_text=True)

	# An open tab of a deleted page loads it again (and gets the 404)
	page = app.test_page("/about")
	(reloader.folder / "pages/about.py").unlink()
	assert reloader.reload([str(reloader.folder / "pages/about.py")]) == "hot"
	assert messages(app, page) == [{"type": "hot", "reload": True}]
	assert client.get("/about").status_code == 404
	assert client.get("/").status_code == 200


@pytest.mark.parametrize("path", ["app.py", "settings.json", "settings.local.json"])
def test_app_and_settings_changes_restart(make_app, path):

	app, reloader = make_app()

	assert change(reloader, path, APP if path == "app.py" else "{}") == "restart"
	assert reloader.restarts == [f"{path} changed"]


def test_restart_exits_for_the_supervisor(make_app, monkeypatch):

	app, reloader = make_app()
	del reloader.restart
	exits = []
	monkeypatch.setattr(os, "_exit", exits.append)

	change(reloader, "app.py", APP + "\n")

	assert exits == [hot.RESTART_EXIT]


def test_syntax_error_shows_in_pages_and_the_old_code_keeps_running(make_app):

	app, reloader = make_app()
	page = app.test_page("/")
	page.click("button", text="+")

	assert change(reloader, "components/counter.py", COUNTER.replace("Count:", "Total:") + "\ndef broken(:\n") == "error"

	(message,) = messages(app, page)
	assert message["type"] == "hot" and message["error"].startswith("SyntaxError")
	assert "counter.py" in message["traceback"]

	# The old code still serves, events included
	page.click("button", text="+")
	assert page.text("p") == "Count: 2"
	assert app.test_page("/").text("p") == "Count: 0"

	# An error at import is undone as well, without changing what the module had
	assert change(reloader, "components/counter.py", COUNTER.replace("Count:", "Total:") + "\nraise RuntimeError('oops')\n") == "error"
	assert app.test_page("/").text("p") == "Count: 0"
	messages(app, page)

	# The next save that works clears the error
	assert change(reloader, "components/counter.py", COUNTER.replace("Count:", "Total:")) == "hot"
	found = messages(app, page)
	assert found[-1] == {"type": "hot", "error": None}
	page.apply(found[0], None)
	assert page.text("p") == "Total: 2"


def test_render_error_after_a_reload_shows_and_the_next_save_clears_it(make_app):

	app, reloader = make_app()
	page = app.test_page("/")

	change(reloader, "components/counter.py", COUNTER.replace('f"Count: {self.count}"', "self.missing"))
	(message,) = messages(app, page)
	assert message["error"].startswith("AttributeError")

	change(reloader, "components/counter.py", COUNTER)
	assert messages(app, page)[-1]["error"] is None


def test_predictions_follow_the_new_handler_code(make_app):

	app, reloader = make_app()
	page = app.test_page("/")

	# The counter ships the state its + button leads to
	assert "Count: 1" in page.html

	change(reloader, "components/counter.py", COUNTER.replace("self.count += 1", "self.count += 5"))
	page.sync()

	assert "Count: 5" in page.html and "Count: 1" not in page.html


def test_modules_that_import_a_changed_module_are_reloaded(make_app):

	files = {
		"helpers.py": "def label(count):\n\n\treturn f'Count: {count}'\n",
		"components/counter.py": COUNTER.replace("from domino import State", "from domino import State\n\nfrom helpers import label").replace('f"Count: {self.count}"', "label(self.count)"),
	}
	app, reloader = make_app(files)
	page = app.test_page("/")
	page.click("button", text="+")

	change(reloader, "helpers.py", "def label(count):\n\n\treturn f'Clicked {count} times'\n")
	page.sync()

	assert page.text("p") == "Clicked 1 times"


def test_module_level_reactive_data_is_kept(make_app):

	files = {"data.py": "from domino import Collection, State\n\nvisits = State(0)\nnotes = Collection()\n"}
	app, reloader = make_app(files)
	import data
	data.visits.value = 3
	data.notes.insert({"text": "kept"})
	visits = data.visits

	change(reloader, "data.py", "from domino import Collection, State\n\nvisits = State(0)\nnotes = Collection()\nother = 1\n")

	assert data.visits is visits and data.visits.value == 3
	assert data.notes.count() == 1 and data.other == 1


def test_modules_that_start_threads_or_define_apps_restart(make_app):

	clock = "import threading\nimport time\n\nimport helpers\n\n\ndef tick():\n\n\ttime.sleep(0)\n\n\nthreading.Thread(target=tick, daemon=True).start()\n"
	files = {"helpers.py": "x = 1\n", "components/clock.py": clock, "pages/index.py": "import components.clock\n" + INDEX}
	app, reloader = make_app(files)

	assert change(reloader, "components/clock.py", clock + "\n") == "restart"
	assert reloader.restarts == ["components/clock.py changed"]

	# It would run again for a module it imports
	reloader.restarts.clear()
	assert change(reloader, "helpers.py", "x = 2\n") == "restart"
	assert reloader.restarts == ["helpers.py changed (components/clock.py can't be hot reloaded)"]

	# Modules it doesn't depend on reload as usual
	assert change(reloader, "components/counter.py", COUNTER.replace("Count:", "Total:")) == "hot"


def test_restart_only_reads_the_module_code(tmp_path):

	def check(code):
		path = tmp_path / "module.py"
		path.write_text(dedent(code), encoding="utf-8")
		return restart_only(path)

	assert check("import threading\nthreading.Thread(target=print).start()\n")
	assert check("from flask import Flask\napp = Flask(__name__)\n")
	assert check("from app import app\n\n@app.route('/x')\ndef x():\n    return 'x'\n")
	assert check("import atexit\natexit.register(print)\n")
	assert check("from app import app\n\n@app.before_request\ndef check():\n    pass\n")
	# Calls inside functions only run later
	assert not check("import threading\n\ndef later():\n    threading.Thread(target=print).start()\n")
	assert not check("import domino.tags as t\nfrom domino import State\n\nclass Counter(t.div):\n    count = State(0)\n")
	# The module decides
	assert not check("import threading\n__hot_reload__ = True\nthreading.Thread(target=print).start()\n")
	assert check("__hot_reload__ = False\nx = 1\n")


def test_paired_template_change_rerenders_the_component_keeping_its_state(make_app):

	files = {
		"components/counter.py": COUNTER.replace("\tdef render(self):\n\n\t\treturn [\n\t\t\tt.p() [f\"Count: {self.count}\"],\n\t\t\tt.button(on_click=self.increment) [\"+\"],\n\t\t]\n\n\n", ""),
		"components/counter.html": "<p>Count: {{ count }}</p>\n<button {{ on(click=increment) }}>+</button>\n",
	}
	app, reloader = make_app(files)
	page = app.test_page("/")
	page.click("button", text="+")
	assert page.text("p") == "Count: 1"

	assert change(reloader, "components/counter.html", "<p>Total: {{ count }}</p>\n<button {{ on(click=increment) }}>+</button>\n") == "hot"
	page.sync()

	assert page.text("p") == "Total: 1"


def test_component_css_change_sends_the_page_css(make_app):

	app, reloader = make_app({"components/counter.py": COUNTER.replace("\tcount = State(0)", "\tcss = {'color': 'red'}\n\tcount = State(0)")})
	page = app.test_page("/")

	change(reloader, "components/counter.py", COUNTER.replace("\tcount = State(0)", "\tcss = {'color': 'blue'}\n\tcount = State(0)"))

	message = messages(app, page)[-1]
	assert message["type"] == "hot"
	assert message["css"] == [["Counter", ".Counter {\n\tcolor: blue;\n}"]]


def test_static_pages_are_kept_and_updated(make_app):

	app, reloader = make_app({"pages/about.py": "import domino.tags as t\n\n\ndef page():\n\n\treturn t.p() ['About']\n"})
	page = app.test_page("/about")
	assert page.page_id and app.page_store.load(page.page_id) is not None

	change(reloader, "pages/about.py", "import domino.tags as t\n\n\ndef page():\n\n\treturn t.p() ['About us']\n")
	page.sync()

	assert page.text("p") == "About us"


def test_files_that_dont_matter_are_ignored(make_app):

	app, reloader = make_app()

	assert change(reloader, "notes.txt", "x") is None
	assert change(reloader, ".domino/mongod.log", "x") is None
	# A module nothing imports yet waits until something does
	assert change(reloader, "components/unused.py", "x = 1\n") is None
	assert change(reloader, "pages/index_test.py", "def test_x():\n\tpass\n") is None
	assert reloader.restarts == []


def test_the_watcher_hands_changes_to_the_reloader(make_app):

	app, reloader = make_app()
	handled = []
	reloader.reload = lambda paths: handled.append(set(paths))
	reloader.start()
	try:
		# Changes are noticed once watching has started, which takes a moment
		deadline = time.monotonic() + 10
		while not handled and time.monotonic() < deadline:
			write(reloader.folder / "components/counter.py", COUNTER + f"\n# {time.monotonic()}\n")
			time.sleep(0.2)
	finally:
		reloader.stop.set()
		reloader.thread.join(5)

	assert handled and str((reloader.folder / "components/counter.py").resolve()) in set.union(*handled)


def test_polling_finds_changes_without_watchfiles(tmp_path):

	import threading

	stop = threading.Event()
	write(tmp_path / "a.py", "x = 1\n")
	changes = hot.poll(str(tmp_path), stop, lambda path: path.endswith(".py"))

	def save():
		time.sleep(0.3)
		write(tmp_path / "a.py", "x = 22\n")

	threading.Thread(target=save, daemon=True).start()
	assert next(changes) == {str(tmp_path / "a.py")}
	stop.set()


# Serving


@pytest.fixture
def served(monkeypatch):

	import uvicorn

	calls = []
	monkeypatch.setattr(uvicorn, "run", lambda target, **kwargs: calls.append(("uvicorn", target, kwargs)))
	monkeypatch.setattr(hot, "serve", lambda target, root, **kwargs: calls.append(("hot", target, root, kwargs)))
	# What serve() sets is undone after the test
	for name in ("DOMINO_ASGI_HOT", "DOMINO_ASGI_APP", "FLASK_DEBUG"):
		monkeypatch.setenv(name, "")
		monkeypatch.delenv(name)

	return calls


def test_debug_serving_hot_reloads(make_app, served):

	app, reloader = make_app()

	domino.asgi.serve(app, "127.0.0.1", 5000, reload=True)

	assert served == [("hot", "domino.asgi:from_environ", app.root_path, {"host": "127.0.0.1", "port": 5000, "timeout_graceful_shutdown": 3, "ws_per_message_deflate": True})]
	assert os.environ["DOMINO_ASGI_HOT"] == "1"


def test_hot_reload_setting_false_restarts_on_changes(make_app, served):

	app, reloader = make_app({"settings.json": '{"domino": {"hot_reload": false}}'})

	domino.asgi.serve(app, "127.0.0.1", 5000, reload=True)

	(call,) = served
	assert call[0] == "uvicorn" and call[2]["reload"] is True
	assert "DOMINO_ASGI_HOT" not in os.environ


def test_production_never_watches(make_app, served):

	app, reloader = make_app()

	domino.asgi.serve(app, "127.0.0.1", 5000)

	assert served[0][0] == "uvicorn" and "reload" not in served[0][2]
	assert "DOMINO_ASGI_HOT" not in os.environ


def test_the_server_process_starts_the_reloader(make_app, monkeypatch):

	app, reloader = make_app()
	started = []
	monkeypatch.setattr(HotReloader, "start", lambda self: started.append(self))
	monkeypatch.setenv("DOMINO_ASGI_APP", f"{reloader.folder / 'app.py'}:app")
	monkeypatch.setenv("DOMINO_ASGI_HOT", "1")

	asgi = domino.asgi.from_environ()

	assert [reloader.app for reloader in started] == [asgi.app]
	assert started[0].app_file == (reloader.folder / "app.py").resolve()


# In a browser, served by `domino run` in a subprocess


BROWSER_COUNTER = COUNTER.replace('''			t.button(on_click=self.increment) ["+"],''', '''			t.button(on_click=self.increment) ["+"],
			t.input(name="note"),''')


@pytest.fixture
def domino_run(tmp_path):
	"""`domino run <folder> --port 0` in a subprocess, with the counter app."""

	processes = []

	def start():

		folder = tmp_path / "live"
		for path, text in {"app.py": APP, "components/counter.py": BROWSER_COUNTER, "pages/index.py": INDEX}.items():
			write(folder / path, text)
		log_path = tmp_path / "run.log"
		log = open(log_path, "w")
		env = dict(os.environ, PYTHONPATH=str(ROOT), DOMINO_NO_MONGO="1")
		env.pop("DOMINO_ASGI_HOT", None)
		command = "import sys; from domino.cli import main; sys.exit(main(sys.argv[1:]))"
		process = subprocess.Popen([sys.executable, "-c", command, "run", str(folder), "--port", "0"],
			stdout=log, stderr=subprocess.STDOUT, env=env, cwd=str(tmp_path), start_new_session=True)
		processes.append((process, log))

		def started():
			assert process.poll() is None, log_path.read_text()
			return re.search(r"App: http://127\.0\.0\.1:([1-9]\d*)/", log_path.read_text())

		wait_until(started, 60, "domino run didn't start")
		port = started().group(1)
		return folder, f"http://127.0.0.1:{port}/", log_path

	yield start

	for process, log in processes:
		if process.poll() is None:
			# The supervisor and the server process it started
			if os.name == "nt":
				subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
				process.wait()
			else:
				os.killpg(process.pid, 15)
				try:
					process.wait(15)
				except subprocess.TimeoutExpired:
					os.killpg(process.pid, 9)
					process.wait()
		log.close()


def test_browser_page_updates_in_place_keeping_state(domino_run):

	playwright = pytest.importorskip("playwright.sync_api")

	folder, url, log_path = domino_run()

	with playwright.sync_playwright() as p:
		browser = p.chromium.launch()
		try:
			page = browser.new_page()
			page.goto(url)
			page.wait_for_function("document.querySelector('[data-domino-ws]') && true")
			page.evaluate("window.marker = 'still here'")
			page.click("text=+")
			page.click("text=+")
			page.wait_for_function("document.querySelector('p').textContent.trim() === 'Count: 2'")
			page.fill("input[name=note]", "typed")
			page.focus("input[name=note]")
			# Changes are noticed once the watcher has started
			time.sleep(1)

			write(folder / "components/counter.py", BROWSER_COUNTER.replace("Count:", "Total:"))
			page.wait_for_function("document.querySelector('p').textContent.trim() === 'Total: 2'", timeout=10000)

			assert page.evaluate("window.marker") == "still here"
			assert page.input_value("input[name=note]") == "typed"
			assert page.evaluate("document.activeElement.name") == "note"
			page.click("text=+")
			page.wait_for_function("document.querySelector('p').textContent.trim() === 'Total: 3'")

			# A syntax error shows in the page, and fixing it clears it
			write(folder / "components/counter.py", BROWSER_COUNTER + "\ndef broken(:\n")
			page.wait_for_selector("#domino-error", timeout=10000)
			assert "SyntaxError" in page.text_content("#domino-error")
			write(folder / "components/counter.py", BROWSER_COUNTER.replace("Count:", "Sum:"))
			page.wait_for_function("document.querySelector('p').textContent.trim() === 'Sum: 3'", timeout=10000)
			assert page.query_selector("#domino-error") is None
			assert page.evaluate("window.marker") == "still here"

			# app.py restarts the server, and the page reloads by itself
			write(folder / "app.py", APP + "\n# changed\n")
			try:
				page.wait_for_function("window.marker === undefined && document.querySelector('p') && document.querySelector('p').textContent.trim() === 'Sum: 0'", timeout=30000)
			except playwright.Error as error:
				raise AssertionError(f"{error}\n{log_path.read_text()}") from None
		finally:
			browser.close()

	output = log_path.read_text()
	assert re.search(r"domino: hot reloaded components/counter\.py \(1 page\) in \d+ ms", output), output
	assert "domino: restarting: app.py changed" in output
