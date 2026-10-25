"""`domino serve --workers N`: worker processes behind a router that sends each page's requests
to the worker that has the page."""

import http.client
import json
import os
import re
import signal
import socket
import sys
import textwrap
from contextlib import contextmanager
from pathlib import Path

import pytest

websockets_client = pytest.importorskip("websockets.sync.client")

import domino._asgi
import domino._workers as workers
from domino import Domino

from conftest import Served, running, wait_until


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="uses POSIX signals")

APP = '''
import os
import threading

from flask import request

import domino.tags as t
from domino import Collection, Domino, State, accounts
from domino import Document


app = Domino(__name__)
app.secret_key = "serve test"
app.config["DOMINO_KEEPALIVE"] = 0.2

# In memory: each worker has its own copy of this user, with the same id
accounts.users = Collection()
accounts.create_user("ada@example.com", "correct horse")
user = accounts.users.find_one({})
accounts.users.remove({})
accounts.users.insert(dict(user, _id="ada"))


class Counter(t.div):

	count = State(0)
	ticks = State(0)


	def render(self):

		return [
			t.p(class_="count") [f"Count: {self.count}"],
			t.p(class_="ticks") [f"Ticks: {self.ticks}"],
			t.button(on_click=self.increment) ["+"],
			t.button(on_click=self.later) ["later"],
		]


	def increment(self):

		self.count += 1


	def later(self):

		# Changed from another thread, so it's pushed
		threading.Timer(0.1, self.tick).start()


	def tick(self):

		self.ticks += 1


@app.route("/")
def index():
	return Document() [Counter()]


@app.route("/login")
def login():
	return Document() [accounts.UserMenu(), accounts.LoginForm()]


@app.route("/worker")
def worker():
	return f"{os.environ['DOMINO_WORKER_ID']} {os.getpid()}"


@app.route("/ip")
def ip():
	return request.remote_addr


@app.route("/echo", methods=["POST"])
def echo():
	# Werkzeug leaves a chunked body unread unless the server says it ends; a2wsgi doesn't
	return request.environ["wsgi.input"].read()
'''


def write(folder, source=APP):

	folder.mkdir(parents=True, exist_ok=True)
	(folder / "app.py").write_text(textwrap.dedent(source), encoding="utf-8")

	return folder


@pytest.fixture
def serve(tmp_path):

	started = []

	def start(count=2, source=APP, name="app"):
		served = Served(write(tmp_path / name, source), count)
		started.append(served)
		return served.start()

	yield start

	for served in started:
		served.stop()


@pytest.fixture(scope="module")
def server(tmp_path_factory):
	"""One served app shared by the tests that don't stop or kill its processes."""

	served = Served(write(tmp_path_factory.mktemp("serve") / "app")).start()
	served.workers()
	yield served
	served.stop()


def parse(html):

	page_id = re.search(r'data-domino-page="([^"]+)"', html).group(1)
	events = re.findall(r'data-event-id="([^"]+)"', html)

	return page_id, events


def load_on(server, worker, path="/"):
	"""Load pages until one is on `worker`."""

	for _ in range(20):
		page_id, events = parse(server.get(path))
		if page_id.startswith(f"w{worker}-"):
			return page_id, events

	raise AssertionError(f"no page on worker {worker}")


def post_event(connection, page_id, event_id, data=None):

	body = json.dumps({"page_id": page_id, "event_id": event_id, "data": data or {}})
	connection.request("POST", "/_domino/events", body, {"Content-Type": "application/json"})
	response = connection.getresponse()

	return response.status, json.loads(response.read())


def receive(ws, timeout=5):

	return json.loads(ws.recv(timeout))


def result(ws):
	"""The next event result, skipping pushed updates."""

	while True:
		message = receive(ws)
		if message["type"] == "result":
			return message


@contextmanager
def hello(server, page_id, **kwargs):

	with websockets_client.connect(f"{server.ws_url}?page={page_id}", open_timeout=5, **kwargs) as ws:
		ws.send(json.dumps({"type": "hello", "page_id": page_id}))
		yield ws


# Routing rules


def test_worker_hints():

	assert workers.worker_hint("/_domino/ws", "page=w3-abc") == 3
	assert workers.worker_hint("/_domino/stream", "page=w12-abc&x=1") == 12
	assert workers.worker_hint("/_domino/session/w2-token", "") == 2
	assert workers.worker_hint("/_domino/session/token", "") is None
	assert workers.worker_hint("/_domino/ws", "page=1234") is None
	assert workers.body_hint(b'{"page_id": "w4-abc", "event_id": "x"}') == 4
	assert workers.body_hint(b'{"page_id": 4}') is None
	assert workers.body_hint(b"not json") is None
	assert workers.body_hint(b"[1]") is None


def test_forwarded_headers_are_kept_only_from_trusted_proxies():

	lines = [b"GET / HTTP/1.1", b"Host: example.com", b"X-Forwarded-For: 203.0.113.9", b"X-Forwarded-Proto: https"]

	trusted = workers.forward_head(lines, "127.0.0.1", {"127.0.0.1"})
	assert trusted == b"GET / HTTP/1.1\r\nHost: example.com\r\nX-Forwarded-Proto: https\r\nX-Forwarded-For: 203.0.113.9, 127.0.0.1\r\n\r\n"

	untrusted = workers.forward_head(lines, "198.51.100.7", {"127.0.0.1"})
	assert untrusted == b"GET / HTTP/1.1\r\nHost: example.com\r\nX-Forwarded-For: 198.51.100.7\r\n\r\n"

	assert b"203.0.113.9" in workers.forward_head(lines, "198.51.100.7", {"*"})


def test_page_ids_and_session_tokens_start_with_the_worker(monkeypatch):

	from domino._core import Page

	assert not Page().id.startswith("w")
	monkeypatch.setenv("DOMINO_WORKER_ID", "7")
	assert Page().id.startswith("w7-")

	app = Domino(__name__)
	app.secret_key = "x"
	with app.test_request_context():
		from flask import session
		session["x"] = 1
		token, cookies = app.session_handoff(session)
	assert token.startswith("w7-") and cookies


def test_app_run_with_workers_serves_its_file(monkeypatch):

	calls = []
	monkeypatch.setattr(workers, "serve", lambda *args: calls.append(args))
	monkeypatch.setattr(domino._asgi, "serve", lambda *args, **kwargs: calls.append("single"))
	monkeypatch.delenv("FLASK_DEBUG", raising=False)

	app = Domino(__name__)
	globals()["module_level_app"] = app
	try:
		app.run(port=8123, workers=3, load_dotenv=False)
	finally:
		del globals()["module_level_app"]

	assert calls == [(f"{Path(__file__).resolve()}:module_level_app", "127.0.0.1", 8123, 3)]

	# Not for an app that the workers can't load again from its file
	calls.clear()
	Domino(__name__).run(workers=3, load_dotenv=False)
	assert calls == ["single"]


# Served


def test_page_loads_spread_across_workers(server):

	prefixes = {parse(server.get("/"))[0].split("-")[0] for _ in range(6)}

	assert prefixes == {"w1", "w2"}


def test_events_over_post_reach_the_worker_with_the_page(server):

	# One keep-alive connection, its requests going to both workers in turn
	connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
	pages = [load_on(server, 1), load_on(server, 2), load_on(server, 1)]

	for clicks in (1, 2):
		for page_id, (increment, *_) in pages:
			status, payload = post_event(connection, page_id, increment)
			assert status == 200, payload
			assert f"Count: {clicks}" in payload["html"]

	connection.close()


def test_websocket_events_and_pushes_go_through_the_router(server):

	for worker in (1, 2):
		page_id, (increment, later) = load_on(server, worker)
		with hello(server, page_id) as ws:
			assert receive(ws) == {"type": "ready"}

			ws.send(json.dumps({"type": "event", "ref": 1, "page_id": page_id, "event_id": increment, "data": {}}))
			result = receive(ws)
			assert result["status"] == 200 and "Count: 1" in result["html"]

			ws.send(json.dumps({"type": "event", "ref": 2, "page_id": page_id, "event_id": later, "data": {}}))
			assert receive(ws)["ref"] == 2
			update = receive(ws)
			assert update["type"] == "update" and "Ticks: 1" in update["html"]


def test_server_sent_events_go_through_the_router(server):

	page_id, (_, later) = load_on(server, 2)

	stream = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
	stream.request("GET", f"/_domino/stream?page={page_id}")
	response = stream.getresponse()
	assert response.status == 200
	assert response.readline() == b": open\n"

	connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
	assert post_event(connection, page_id, later)[0] == 200

	while True:
		line = response.readline()
		assert line, "the stream ended"
		if line.startswith(b"data: "):
			assert "Ticks: 1" in json.loads(line[6:])["html"]
			break

	stream.close()
	connection.close()


def test_login_over_the_websocket_hands_the_session_over_on_its_worker(server):

	for worker in (1, 2):
		page_id, events = load_on(server, worker, "/login")
		submit = next(event for event in events if event.endswith("-submit"))

		with hello(server, page_id) as ws:
			assert receive(ws) == {"type": "ready"}
			form = {"email": "ada@example.com", "password": "correct horse"}
			ws.send(json.dumps({"type": "event", "ref": 1, "page_id": page_id, "event_id": submit, "data": {"form": form}}))
			answer = result(ws)

		assert answer["status"] == 200, answer
		assert answer["session"].startswith(f"w{worker}-")

		# Only the worker that made the token has it
		connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
		connection.request("POST", f"/_domino/session/{answer['session']}", headers={"X-Domino-Page": page_id})
		response = connection.getresponse()
		response.read()
		assert response.status == 204
		cookie = response.getheader("Set-Cookie").split(";")[0]

		# The cookie is signed with the app's secret key, so every worker accepts it
		for _ in range(2):
			assert "Signed in as" in server.get("/login", {"Cookie": cookie})


def test_origin_is_checked_through_the_router(server):

	page_id, _ = load_on(server, 1)

	with pytest.raises(Exception, match="403"):
		with hello(server, page_id, origin="http://evil.example"):
			pass

	with hello(server, page_id, origin=f"http://127.0.0.1:{server.port}") as ws:
		assert receive(ws) == {"type": "ready"}


def test_workers_see_the_client_address(server):

	assert server.get("/ip") == "127.0.0.1"
	# From a trusted proxy (127.0.0.1, as for uvicorn) its X-Forwarded-For is kept
	assert server.get("/ip", {"X-Forwarded-For": "203.0.113.9"}) == "203.0.113.9"


def test_request_bodies_and_bad_requests(server):

	connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
	body = b"x" * 300000
	connection.request("POST", "/echo", body)
	assert connection.getresponse().read() == body

	# A body of unknown length: the rest of the connection goes to that worker
	connection.request("POST", "/echo", iter([b"chunk ", b"by chunk"]), encode_chunked=True)
	assert connection.getresponse().read() == b"chunk by chunk"
	connection.close()

	for head in (b"GET / HTTP/1.1\r\nX-Big: " + b"x" * 70000 + b"\r\n\r\n",
			b"POST /echo HTTP/1.1\r\nContent-Length: 1\r\nContent-Length: 2\r\n\r\nab",
			b"nonsense\r\n\r\n"):
		with socket.create_connection(("127.0.0.1", server.port), 10) as raw:
			raw.sendall(head)
			assert raw.recv(100).split(b" ")[1] in (b"400", b"431")


def test_unknown_pages_and_tokens_are_not_found(server):

	connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
	assert post_event(connection, "w9-nope", "x")[0] == 404
	connection.request("POST", "/_domino/session/w1-nope", headers={"X-Domino-Page": "w1-page"})
	assert connection.getresponse().status == 404

	with hello(server, "w2-nope") as ws:
		assert receive(ws) == {"type": "expired"}


# Processes


def test_killed_worker_is_restarted_and_its_pages_expire(serve):

	served = serve()
	pids = served.workers()
	page_id, (increment, *_) = load_on(served, 1)
	other_id, (other_increment, *_) = load_on(served, 2)

	os.kill(pids[1], signal.SIGKILL)
	wait_until(lambda: served.workers()[1] != pids[1], 30, "worker 1 wasn't restarted")
	assert "worker 1 exited" in served.output()

	# Its pages are gone: the browser reloads them
	connection = http.client.HTTPConnection("127.0.0.1", served.port, timeout=10)
	assert post_event(connection, page_id, increment)[0] == 404
	with hello(served, page_id) as ws:
		assert receive(ws) == {"type": "expired"}

	# The other worker's pages, and new pages on the new worker, work
	assert post_event(connection, other_id, other_increment)[0] == 200
	page_id, (increment, *_) = load_on(served, 1)
	assert post_event(connection, page_id, increment)[0] == 200
	connection.close()


def test_graceful_shutdown_stops_every_worker(serve):

	served = serve(3)
	pids = served.workers(3)
	page_id, _ = load_on(served, 3)
	with hello(served, page_id) as ws:
		assert receive(ws) == {"type": "ready"}

		# With a WebSocket open, which the worker closes as it stops
		served.process.send_signal(signal.SIGTERM)
		assert served.process.wait(15) == 0

	wait_until(lambda: not any(running(pid) for pid in pids.values()), 10, "workers outlived the router")


def test_killed_router_takes_its_workers_with_it(serve):

	served = serve()
	pids = served.workers()

	served.process.kill()
	served.process.wait()

	wait_until(lambda: not any(running(pid) for pid in pids.values()), 15, "workers outlived the router")


def test_a_worker_that_fails_to_start_stops_serve(tmp_path):

	served = Served(write(tmp_path / "broken", "raise RuntimeError('broken app')\n"))
	try:
		assert served.process.wait(60) == 1
		output = served.output()
		assert "broken app" in output
		assert "exited while starting" in output
	finally:
		served.stop()
