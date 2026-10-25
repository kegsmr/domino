"""Client components (domino.client): checking their modules, rendering them on the server with
the code the browser runs, and what the app serves the browser. tests/test_client_browser.py runs
them in a real browser."""

import base64
import hashlib
import importlib
import io
import json
import os
import re
import sys
import tarfile
import textwrap

import pytest

import domino.tags as t
from domino import Domino, State, client
from domino.client import ClientComponentError
from domino.components import Document


COUNTER = '''
	import domino.tags as t
	from domino import State


	class Clicks(t.div):

		client = True

		count = State(0)
		label = State("Clicks")

		css = {"button": {"font_weight": "bold"}}


		def render(self):

			return [
				t.p() [f"{self.label}: {self.count}"],
				t.button(type="button", on_click=self.increment) ["+"],
				t.button(type="button", on_click=lambda event: self.add(10)) ["+10"],
				t.input(value=str(self.count), on_input=self.typed),
			]


		def increment(self):

			self.count += 1


		def add(self, amount):

			self.count += amount


		def typed(self, event):

			self.count = int(event.value or 0)
'''


@pytest.fixture(autouse=True)
def clean_environ(monkeypatch):

	for name in list(os.environ):
		if name.startswith("DOMINO_"):
			monkeypatch.delenv(name)


@pytest.fixture
def make_module(tmp_path):
	"""Write a module into a folder on the import path and import it: client components are sent
	to the browser from their source file."""

	sys.path.insert(0, str(tmp_path))
	imported = []

	def make(name, source):
		(tmp_path / f"{name}.py").write_text(textwrap.dedent(source), encoding="utf-8")
		imported.append(name)
		sys.modules.pop(name, None)
		importlib.invalidate_caches()
		return importlib.import_module(name)

	yield make

	sys.path.remove(str(tmp_path))
	for name in imported:
		sys.modules.pop(name, None)
		client.modules.pop(name, None)


def render_page(app, page):

	app.route("/")(page)

	return app.test_client().get("/").get_data(as_text=True)


def state_of(html, cls="Clicks"):

	match = re.search(rf'<div class="{cls}[" ][^>]*data-domino-state="([^"]*)"', html)
	assert match, html

	return json.loads(match.group(1).replace("&#34;", '"'))


# Checking modules when they're imported


def test_a_client_component_registers_its_module(make_module):

	module = make_module("clicks_ok", COUNTER)

	registered = client.modules["clicks_ok"]
	assert registered.classes == ["Clicks"]
	assert registered.source == textwrap.dedent(COUNTER)
	assert registered.key == f"clicks_ok@{registered.hash}"
	assert client.classes[module.Clicks] is registered


@pytest.mark.parametrize("line, message", [
	("from domino import Collection", "can't import Collection from domino: Collections live on the server"),
	("from domino import accounts", "can't import accounts from domino: accounts live on the server"),
	("import os", "can't import os"),
	("import domino", "can't import domino"),
	("from flask import request", "can't import from flask"),
	("from .helpers import secret", "can't use relative imports"),
	("from domino.mongo import connect", "can't import from domino.mongo"),
])
def test_imports_of_server_code_stop_the_app_at_startup(make_module, line, message):

	# Checked when the class is defined, before the rest of the module runs
	source = f"import domino.tags as t\n\n\nclass Bad(t.div):\n\n\tclient = True\n\n\n{line}\n"

	with pytest.raises(ClientComponentError) as error:
		make_module("bad_import", source)

	text = str(error.value)
	assert message in text
	# Where, and why it matters
	assert "bad_import.py:9: Bad has client = True, so all of" in text
	assert "is sent to the browser" in text
	assert "math, random, time" in text


def test_imports_inside_functions_are_checked_too(make_module):

	source = "import domino.tags as t\n\n\nclass Bad(t.div):\n\n\tclient = True\n\n\tdef save(self):\n\t\timport subprocess\n"

	with pytest.raises(ClientComponentError, match=r"bad_inner.py:9: .*can't import subprocess"):
		make_module("bad_inner", source)


def test_allowed_imports_pass(make_module):

	make_module("good_imports", '''
		import json
		import math
		import random
		import time

		import domino.tags as t
		from domino import State, tags
		from domino.tags import div


		class Fine(div):
			client = True
			value = State(1.5)
	''')

	assert client.modules["good_imports"].classes == ["Fine"]


def test_state_must_hold_json_values(make_module):

	with pytest.raises(ClientComponentError, match=r"Odd.seen: State\(...\) of a client component must hold JSON values"):
		make_module("bad_state", "import domino.tags as t\nfrom domino import State\n\nclass Odd(t.div):\n\tclient = True\n\tseen = State({1, 2})\n")


def test_client_components_cant_be_live(make_module):

	with pytest.raises(ClientComponentError, match="can't be live"):
		make_module("bad_live", "import domino.tags as t\n\nclass Pushed(t.div):\n\tclient = True\n\tlive = True\n")


def test_a_server_subclass_of_a_client_component_is_an_ordinary_component(make_module):

	module = make_module("clicks_sub", COUNTER)

	class ServerClicks(module.Clicks):
		client = False

	assert ServerClicks not in client.classes

	app = Domino(__name__)
	html = render_page(app, lambda: Document()[ServerClicks()])

	assert 'class="ServerClicks Clicks"' in html
	assert "data-domino-client" not in html
	assert "data-event-id" in html  # its handlers run on the server


# Rendering on the server


def test_the_server_renders_the_first_html_with_the_browsers_code(make_module):

	make_module("clicks_ssr", COUNTER)
	from clicks_ssr import Clicks

	app = Domino(__name__)
	html = render_page(app, lambda: Document(title="Clicks")[Clicks()])

	key = client.modules["clicks_ssr"].key
	assert f'data-domino-client="{key}:Clicks"' in html
	assert "<p>Clicks: 0</p>" in html
	# Bound for the browser to run, not registered on the server
	assert 'data-domino-on="click:0"' in html
	assert 'data-domino-on="click:1"' in html
	assert 'data-domino-on="input:2"' in html
	assert "data-event-id" not in html
	# Class-level css is still written by the server, in the head
	assert ".Clicks button" in html.split("</head>")[0]
	assert state_of(html) == {"state": {"count": 0, "label": "Clicks"}, "attrs": {}}


def test_state_and_attributes_set_on_the_server_are_sent_along(make_module):

	make_module("clicks_state", COUNTER)
	from clicks_state import Clicks

	def page():
		clicks = Clicks(class_="wide", data_mode="compact", style={"max_width": "20rem"})
		clicks.count = 5
		return Document()[clicks]

	html = render_page(Domino(__name__), page)

	assert "<p>Clicks: 5</p>" in html
	assert 'class="Clicks wide"' in html
	assert 'data-mode="compact"' in html
	assert 'style="max-width: 20rem"' in html
	assert state_of(html) == {
		"state": {"count": 5, "label": "Clicks"},
		"attrs": {"class_": "wide", "data_mode": "compact", "style": {"max_width": "20rem"}},
	}


def test_attributes_that_arent_json_are_refused(make_module):

	make_module("clicks_attrs", COUNTER)
	from clicks_attrs import Clicks

	app = Domino(__name__)
	app.testing = True
	app.route("/")(lambda: Document()[Clicks(data_when=object())])

	with pytest.raises(ClientComponentError, match=r"Clicks\(data_when=.*only JSON values"):
		app.test_client().get("/")


def test_inside_a_server_component_with_a_server_handler(make_module):

	make_module("clicks_inside", COUNTER)
	from clicks_inside import Clicks

	received = []

	class Board(t.section):

		saved = State(0)

		def render(self):
			return [Clicks(on_save=self.save), t.p() [f"Saved {self.saved}"]]

		def save(self, event):
			received.append(event.value)
			self.saved += 1

	app = Domino(__name__)
	client_ = app.test_client()
	app.route("/")(lambda: Document()[Board()])
	html = client_.get("/").get_data(as_text=True)

	# The server handler is bound on the client component's root, for self.emit("save", ...)
	event_id = re.search(r'<div class="Clicks"[^>]* data-event-id="([^"]+-save)"', html).group(1)
	page_id = re.search(r'data-domino-page="([^"]+)"', html).group(1)
	response = client_.post("/_domino/events", json={"page_id": page_id, "event_id": event_id, "data": {"value": {"count": 3}}})

	assert response.status_code == 200
	assert received == [{"count": 3}]
	answer = response.get_json()
	assert "Saved 1" in answer["html"]
	# The client component comes again in the server's HTML; core.js keeps the running one
	assert "data-domino-client" in answer["html"]


def test_the_browsers_render_matches_the_servers(make_module):

	make_module("clicks_same", COUNTER)
	from clicks_same import Clicks

	html = render_page(Domino(__name__), lambda: Document()[Clicks()])
	ssr = re.search(r'<div class="Clicks".*?</div>', html, re.S).group(0)
	element_id = re.search(r'id="([^"]+)"', ssr).group(1)

	shim = client.shim()
	key = client.modules["clicks_same"].key
	answer = json.loads(shim.mount(element_id, key, "Clicks", json.dumps(state_of(html))))

	assert answer == {"html": True, "events": ["click", "input"], "after": [], "emit": []}
	mounted = shim.html(element_id)
	# The same but for the state the browser has taken over, and the mark that it has
	assert mounted == re.sub(r' data-domino-state="[^"]*"', "", ssr).replace(">", " data-domino-hydrated>", 1)


def test_pages_render_client_components_in_parallel(make_module):

	make_module("clicks_threads", COUNTER)
	from clicks_threads import Clicks
	from concurrent.futures import ThreadPoolExecutor

	app = Domino(__name__)
	app.route("/")(lambda: Document()[Clicks(), Clicks()])

	def load(_):
		return app.test_client().get("/").get_data(as_text=True)

	with ThreadPoolExecutor(8) as pool:
		pages = list(pool.map(load, range(40)))

	for html in pages:
		# Each render numbers its own handlers, whatever the other threads do
		assert html.count('data-domino-on="click:0"') == 2
		assert html.count('data-domino-on="input:2"') == 2


# The browser's runtime, run here


def mounted(make_module, name, source, data=None):

	make_module(name, source)
	shim = client.shim()
	module = client.modules[name]
	if module.key not in shim.modules:
		shim.load_module(module.key, module.source, client.shim_builtins(shim), module.path)
	element_id = f"{name}-root"
	answer = json.loads(shim.mount(element_id, module.key, module.classes[0], json.dumps(data or {})))
	assert "error" not in answer, answer

	return shim, element_id


def test_handlers_change_state_and_render_again(make_module):

	shim, element_id = mounted(make_module, "clicks_run", COUNTER)
	event = json.dumps({"type": "click"})

	assert json.loads(shim.dispatch(element_id, "event", 0, event))["html"] is True
	assert "<p>Clicks: 1</p>" in shim.html(element_id)

	# A lambda without the event's argument, and a handler reading event.value
	shim.dispatch(element_id, "event", 1, event)
	assert "<p>Clicks: 11</p>" in shim.html(element_id)
	shim.dispatch(element_id, "event", 2, json.dumps({"type": "input", "value": "42"}))
	assert "<p>Clicks: 42</p>" in shim.html(element_id)


def test_nothing_changed_means_no_render(make_module):

	shim, element_id = mounted(make_module, "clicks_same_value", COUNTER, {"state": {"count": 7}})

	answer = json.loads(shim.dispatch(element_id, "event", 2, json.dumps({"type": "input", "value": "7"})))

	assert answer["html"] is False


def test_errors_come_back_with_a_traceback(make_module):

	shim, element_id = mounted(make_module, "clicks_error", COUNTER)

	answer = json.loads(shim.dispatch(element_id, "event", 2, json.dumps({"type": "input", "value": "many"})))

	assert answer["error"].startswith("ValueError")
	assert "clicks_error.py\", line 38, in typed" in answer["traceback"]
	assert "int(event.value or 0)" in answer["traceback"]


def test_after_timers_and_emit(make_module):

	shim, element_id = mounted(make_module, "ticker", '''
		import domino.tags as t
		from domino import State


		class Ticker(t.div):

			client = True
			ticks = State(0)


			def render(self):

				if self.ticks < 2:
					self.after(50, self.tick)
				return [t.span() [str(self.ticks)], t.button(on_click=self.send) ["send"]]


			def tick(self):

				self.ticks += 1


			def send(self):

				self.emit("done", {"ticks": self.ticks})
	''')

	assert json.loads(shim.dispatch(element_id, "after", 0, ""))["after"] == [[0, 50]]
	assert json.loads(shim.dispatch(element_id, "after", 0, ""))["after"] == []
	# A timer of a render that no longer schedules it does nothing
	assert json.loads(shim.dispatch(element_id, "after", 0, "")) == {"html": False, "events": [], "after": [], "emit": []}
	assert json.loads(shim.dispatch(element_id, "event", 0, json.dumps({"type": "click"})))["emit"] == [["done", {"ticks": 2}]]


def test_example_components_render_with_the_shim(load_example):

	html = load_example("client").app.test_client().get("/").get_data(as_text=True)

	assert html.count('data-domino-client="components.life@') == 1
	assert html.count('data-domino-client="components.stats@') == 1
	assert 'class="ServerTextStats TextStats"' in html


# What the app serves


def test_loader_has_the_settings_and_the_shim():

	app = Domino(__name__)
	response = app.test_client().get("/_domino/client/loader.js")

	assert response.status_code == 200
	assert response.mimetype == "text/javascript"
	text = response.get_data(as_text=True)
	config = json.loads(text.split("\n", 1)[0][len("const CONFIG = "):-1])
	assert config["python"] == "micropython"
	# Not debugging: the CDN
	assert config["url"] == "https://cdn.jsdelivr.net/npm/@micropython/micropython-webassembly-pyscript@1.29.0-6/"
	assert set(config["shim"]) == {"domino/__init__.py", "domino/tags.py"}
	assert "def dispatch(" in config["shim"]["domino/__init__.py"]
	assert "export function hydrate" in text


def test_debugging_serves_the_runtime_locally():

	app = Domino(__name__)
	app.debug = True

	assert client.runtime_url(app) == "/_domino/client/runtime/"


def test_runtime_settings(monkeypatch):

	monkeypatch.setenv("DOMINO_DOMINO__CLIENT_RUNTIME", "https://static.example.com/pyodide")
	monkeypatch.setenv("DOMINO_DOMINO__CLIENT_PYTHON", "pyodide")
	app = Domino(__name__)

	text = app.test_client().get("/_domino/client/loader.js").get_data(as_text=True)

	assert '"python": "pyodide"' in text
	assert '"url": "https://static.example.com/pyodide/"' in text


def test_cdn_setting_follows_the_runtime():

	app = Domino(__name__)
	app.debug = True
	app.config["DOMINO_CLIENT_RUNTIME"] = "cdn"
	app.config["DOMINO_CLIENT_PYTHON"] = "pyodide"

	assert client.runtime_url(app) == "https://cdn.jsdelivr.net/npm/pyodide@314.0.7/"


def test_unknown_python_is_an_error():

	app = Domino(__name__)
	app.config["DOMINO_CLIENT_PYTHON"] = "brython"

	with pytest.raises(ClientComponentError, match="Unknown client Python 'brython'"):
		client.loader_js(app)


def test_only_client_modules_are_served(make_module):

	make_module("clicks_served", COUNTER)
	make_module("server_only", "SECRET = 'hunter2'\n")
	module = client.modules["clicks_served"]
	http = Domino(__name__).test_client()

	response = http.get(f"/_domino/client/module/clicks_served.py?v={module.hash}")
	assert response.status_code == 200
	assert response.get_data(as_text=True) == module.source
	assert "immutable" in response.headers["Cache-Control"]
	assert http.get("/_domino/client/module/clicks_served.py").headers["Cache-Control"] == "no-cache"

	assert http.get("/_domino/client/module/server_only.py").status_code == 404
	assert http.get("/_domino/client/module/os.py").status_code == 404


def test_runtime_files_are_served_only_when_local(tmp_path, monkeypatch):

	for name in client.RUNTIMES["micropython"]["files"]:
		(tmp_path / name).write_bytes(b"\0asm" if name.endswith(".wasm") else b"export {}")
	monkeypatch.setattr(client, "ensure_runtime", lambda name: tmp_path)
	app = Domino(__name__)
	http = app.test_client()

	assert http.get("/_domino/client/runtime/micropython.wasm").status_code == 404

	app.config["DOMINO_CLIENT_RUNTIME"] = "local"
	wasm = http.get("/_domino/client/runtime/micropython.wasm")
	assert wasm.status_code == 200
	assert wasm.mimetype == "application/wasm"
	assert http.get("/_domino/client/runtime/micropython.mjs").mimetype == "text/javascript"
	assert http.get("/_domino/client/runtime/settings.json").status_code == 404


# Downloading the runtime


def fake_package(files):

	buffer = io.BytesIO()
	with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
		for name, data in files.items():
			info = tarfile.TarInfo(f"package/{name}")
			info.size = len(data)
			archive.addfile(info, io.BytesIO(data))

	data = buffer.getvalue()
	integrity = "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()

	return data, integrity


def test_the_runtime_is_downloaded_once_and_checked(tmp_path, monkeypatch):

	data, integrity = fake_package({"micropython.mjs": b"export {}", "micropython.wasm": b"\0asm", "README.md": b"x"})
	monkeypatch.setitem(client.RUNTIMES, "micropython", dict(client.RUNTIMES["micropython"], integrity=integrity))
	downloads = []

	def download(runtime, folder):
		downloads.append(runtime["package"])
		(folder / "package.tgz").write_bytes(data)
		return folder / "package.tgz"

	monkeypatch.setattr(client, "download_package", download)
	environ = {"DOMINO_HOME": str(tmp_path)}

	folder = client.ensure_runtime("micropython", environ)

	assert folder == tmp_path / "client-runtime" / "micropython-webassembly-pyscript@1.29.0-6"
	assert sorted(path.name for path in folder.iterdir()) == ["micropython.mjs", "micropython.wasm"]
	assert client.ensure_runtime("micropython", environ) == folder
	assert downloads == ["@micropython/micropython-webassembly-pyscript"]


def test_a_tampered_runtime_is_refused(tmp_path, monkeypatch):

	data, _ = fake_package({"micropython.mjs": b"evil()", "micropython.wasm": b"\0asm"})

	def download(runtime, folder):
		(folder / "package.tgz").write_bytes(data)
		return folder / "package.tgz"

	monkeypatch.setattr(client, "download_package", download)

	with pytest.raises(ClientComponentError, match="Checksum mismatch"):
		client.ensure_runtime("micropython", {"DOMINO_HOME": str(tmp_path)})

	assert not (tmp_path / "client-runtime" / "micropython-webassembly-pyscript@1.29.0-6").exists()
