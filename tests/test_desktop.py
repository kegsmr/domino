"""Desktop apps (domino.desktop): the server answers only the window that has its token, and
what `domino build --desktop` packages."""

import asyncio
import os
import json
import urllib.error
import urllib.request

import pytest

from domino import Domino, State, desktop
import domino.tags as t


TOKEN = "the-launch-token"


class Counter(t.div):

	count = State(0)


	def render(self):

		return [t.button(on_click=self.increment) [f"Count: {self.count}"]]


	def increment(self):

		self.count += 1


@pytest.fixture
def window_server(asgi_server, monkeypatch):
	"""An app served as `domino desktop` serves it, with the token in its environment."""

	monkeypatch.setenv(desktop.ENV_TOKEN, TOKEN)

	app = Domino(__name__)

	@app.route("/")
	def index():
		return Counter()

	return asgi_server(app)


class NoRedirects(urllib.request.HTTPRedirectHandler):

	def redirect_request(self, *args):

		return None


def test_without_the_token_nothing_is_served(window_server):

	with pytest.raises(urllib.error.HTTPError) as error:
		urllib.request.urlopen(window_server.url)
	assert error.value.code == 403

	# Nor with a wrong one
	with pytest.raises(urllib.error.HTTPError) as error:
		urllib.request.urlopen(window_server.url + "?domino_desktop=guess")
	assert error.value.code == 403


def test_the_first_url_sets_the_cookie_and_leaves_the_token_out(window_server):

	opener = urllib.request.build_opener(NoRedirects())
	with pytest.raises(urllib.error.HTTPError) as answer:
		opener.open(window_server.url + f"about?x=1&domino_desktop={TOKEN}")

	assert answer.value.code == 303
	assert answer.value.headers["Location"] == "/about?x=1"
	cookie = answer.value.headers["Set-Cookie"]
	assert cookie.startswith(f"domino_desktop={TOKEN};")
	assert "HttpOnly" in cookie and "SameSite=Strict" in cookie


def test_the_window_gets_the_page_and_its_socket_works(window_server):

	import websockets.sync.client

	opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
	html = opener.open(desktop.first_url(window_server.port, TOKEN)).read().decode()
	assert "Count: 0" in html
	page_id = html.split('data-domino-page="')[1].split('"')[0]
	event_id = html.split('data-event-id="')[1].split('"')[0]

	url = f"ws://127.0.0.1:{window_server.port}/_domino/ws"
	headers = {"Origin": window_server.url.rstrip("/"), "Cookie": f"domino_desktop={TOKEN}"}
	with websockets.sync.client.connect(url, additional_headers=headers) as socket:
		socket.send(json.dumps({"type": "hello", "page_id": page_id}))
		socket.recv(timeout=10)
		socket.send(json.dumps({"type": "event", "id": 1, "event_id": event_id, "event": {"type": "click"}}))
		while True:
			message = socket.recv(timeout=10)
			if "Count: 1" in message:
				break


def test_a_socket_without_the_token_is_refused(window_server):

	import websockets.sync.client
	from websockets.exceptions import InvalidStatus

	url = f"ws://127.0.0.1:{window_server.port}/_domino/ws"
	with pytest.raises(InvalidStatus):
		websockets.sync.client.connect(url, additional_headers={"Origin": window_server.url.rstrip("/")})


def test_apps_not_run_as_desktop_apps_are_unchanged(asgi_server, monkeypatch):

	monkeypatch.delenv(desktop.ENV_TOKEN, raising=False)

	app = Domino(__name__)

	@app.route("/")
	def index():
		return Counter()

	assert "Count: 0" in urllib.request.urlopen(asgi_server(app).url).read().decode()


def test_admit_lets_lifespan_through():

	sent = []

	async def send(message):
		sent.append(message)

	assert asyncio.run(desktop.admit(TOKEN, {"type": "lifespan"}, None, send))
	assert sent == []


def test_window_options_come_from_settings(tmp_path):

	(tmp_path / "pages").mkdir()
	assert desktop.options(tmp_path / "pages")["title"] == "Pages"

	app = tmp_path / "my_notes"
	(app / "pages").mkdir(parents=True)
	assert desktop.options(app) == {"title": "My Notes", "width": 1024, "height": 768}

	(app / "settings.json").write_text(json.dumps({"desktop": {"title": "Notes", "width": 400, "height": 300}}), encoding="utf-8")
	assert desktop.options(app) == {"title": "Notes", "width": 400, "height": 300}


def test_what_gets_packaged(tmp_path):

	app = tmp_path / "app"
	(app / "pages").mkdir(parents=True)
	(app / "components").mkdir()
	(app / "app.py").write_text("import domino\nfrom domino import Domino\napp = Domino(__name__)\n", encoding="utf-8")
	(app / "data.py").write_text("import requests\nfrom PIL import Image\n", encoding="utf-8")
	(app / "pages" / "index.py").write_text("import data\nfrom components.card import Card\nfrom .x import y\nimport markdown.extensions\n", encoding="utf-8")
	(app / "pages" / "index_test.py").write_text("import pytest\n", encoding="utf-8")
	(app / "components" / "card.py").write_text("x = 1\n", encoding="utf-8")
	(app / ".domino").mkdir()
	(app / ".domino" / "tailwind.css").write_text("css", encoding="utf-8")
	(app / ".domino" / "mongo.log").write_text("log", encoding="utf-8")
	(app / "__pycache__").mkdir()

	# Third-party modules only: not the app's own, nor Domino, nor tests' imports
	assert desktop.imported_modules(app) == ["PIL", "markdown", "requests"]

	target = tmp_path / "packaged"
	desktop.copy_app(app, target)
	files = sorted(path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file())
	assert files == [".domino/tailwind.css", "app.py", "components/card.py", "data.py", "pages/index.py"]


def test_desktop_command_needs_an_app(tmp_path):

	from domino.cli import main

	assert main(["desktop", str(tmp_path)]) == 1


def test_a_packaged_app_is_titled_after_its_own_folder(tmp_path):

	# Packaged, the app's files are in a folder called "app"; the launcher passes the real name
	app = tmp_path / "app"
	(app / "pages").mkdir(parents=True)
	assert desktop.options(app, "my-notes")["title"] == "My Notes"


def test_the_server_stops_when_its_window_process_is_gone(tmp_path):

	import subprocess
	import sys

	# A process standing in for `domino run` watches the one that started it, which ends at once
	code = (
		"import os, signal, sys, time\n"
		"from domino import desktop\n"
		"signal.signal(signal.SIGINT, lambda *args: sys.exit(7))\n"
		f"open({str(tmp_path / 'started')!r}, 'w').close()\n"
		"desktop.watch_parent()\n"
		"time.sleep(30)\n"
	)
	# As `domino desktop` starts `domino run`: its own pid in the child's environment
	spawn = (f"import os, subprocess, sys; env = dict(os.environ, {desktop.ENV_PARENT}=str(os.getpid())); "
		f"print(subprocess.Popen([sys.executable, '-c', {code!r}], env=env).pid)")
	parent = subprocess.Popen([sys.executable, "-c", spawn], stdout=subprocess.PIPE, text=True)
	child = int(parent.stdout.readline())
	parent.wait()

	from conftest import running, wait_until

	try:
		wait_until((tmp_path / "started").exists, message="the child didn't start")
		wait_until(lambda: not running(child), message="the child kept running after its parent ended")
	finally:
		if running(child):
			os.kill(child, 9)
