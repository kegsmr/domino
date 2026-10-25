"""The ASGI app (app.asgi): one WebSocket per tab for events and pushes, served by uvicorn."""

import http.client
import json
import threading
import time
import urllib.request
from contextlib import contextmanager

import pytest

websockets_client = pytest.importorskip("websockets.sync.client")

import domino.tags as t
from domino import Domino
from domino.components import Document


class Counter(t.div):

	live = True


	def __init__(self, *args, **kwargs):

		super().__init__(*args, **kwargs)

		self.count = 0


	def render(self):

		self([
			t.p() [
				f"Count: {self.count}"
			],
			button := t.button() [
				"+"
			],
			slow := t.button() [
				"slow"
			],
			broken := t.button() [
				"broken"
			],
			cookie := t.button() [
				"cookie"
			]
		])

		button.bind("click", self.increment)
		slow.bind("click", self.slow)
		broken.bind("click", self.broken)
		cookie.bind("click", self.cookie)


	def increment(self):

		self.count += 1

		return self


	def slow(self):

		time.sleep(1)

		return self


	def broken(self):

		raise RuntimeError("broken handler")


	def cookie(self):

		from flask import request, url_for

		self.count = f"{request.cookies.get('flavor')} {url_for('index')}"

		return self


def make_app(counter=None):

	app = Domino(__name__)
	app.config["DOMINO_KEEPALIVE"] = 0.1

	@app.route("/")
	def index():
		return Document() [
			Counter() if counter is None else counter  # an empty element is falsy
		]

	@app.route("/plain")
	def plain():
		return Document() [
			t.p() [
				"static"
			]
		]

	return app


def load(server):

	html = urllib.request.urlopen(server.url).read().decode()
	page_id = html.split('data-domino-page="')[1].split('"')[0]
	event_ids = [part.split('"')[0] for part in html.split('data-event-id="')[1:]]

	return html, page_id, event_ids


@contextmanager
def connect(server, page_id=None, **kwargs):

	with websockets_client.connect(server.ws_url, open_timeout=5, **kwargs) as ws:
		if page_id is not None:
			ws.send(json.dumps({"type": "hello", "page_id": page_id}))
			assert receive(ws) == {"type": "ready"}
		yield ws


def receive(ws, timeout=5):

	return json.loads(ws.recv(timeout))


def event(ws, ref, page_id, event_id, data=None):

	ws.send(json.dumps({"type": "event", "ref": ref, "page_id": page_id, "event_id": event_id, "data": data or {}}))


def test_pages_served_over_asgi_are_marked_for_the_websocket(asgi_server):

	app = make_app()
	html = load(asgi_server(app))[0]

	assert "data-domino-ws" in html
	# Plain WSGI (gunicorn, the test client) can't take WebSockets, so its pages aren't marked
	assert "data-domino-ws" not in app.test_client().get("/").get_data(as_text=True)


def test_the_websocket_setting_turns_it_off(asgi_server):

	app = make_app()
	app.config["DOMINO_WEBSOCKET"] = False
	server = asgi_server(app)

	assert "data-domino-ws" not in load(server)[0]
	with pytest.raises(Exception):
		with connect(server):
			pass


def test_hello_then_events_get_results_with_their_ref(asgi_server):

	counter = Counter()
	server = asgi_server(make_app(counter))
	_, page_id, (increment, *_) = load(server)

	with connect(server, page_id) as ws:
		for ref in ("a", "b", "c"):
			event(ws, ref, page_id, increment)
		results = [receive(ws) for _ in range(3)]

	# In the order sent, each with what POST /_domino/events would answer, plus its status
	assert [result["ref"] for result in results] == ["a", "b", "c"]
	assert [result["version"] for result in results] == [1, 2, 3]
	assert all(result["type"] == "result" and result["status"] == 200 for result in results)
	assert results[-1]["id"] == counter.id()
	assert "Count: 3" in results[-1]["html"]
	assert set(results[0]) == {"type", "ref", "status", "id", "html", "version"}


def test_results_match_the_http_endpoint(asgi_server):

	app = make_app()
	server = asgi_server(app)
	_, page_id, (increment, *_) = load(server)

	request = urllib.request.Request(server.url + "_domino/events", method="POST", headers={"Content-Type": "application/json"},
		data=json.dumps({"page_id": page_id, "event_id": increment}).encode())
	over_http = json.loads(urllib.request.urlopen(request).read())

	with connect(server, page_id) as ws:
		event(ws, 1, page_id, increment)
		over_ws = receive(ws)

	assert set(over_ws) - {"type", "ref", "status"} == set(over_http)
	assert over_http["version"] == 1 and over_ws["version"] == 2
	assert over_http["html"].replace("Count: 1", "Count: 2") == over_ws["html"]


def test_errors_and_unknown_events_come_back_with_their_status(asgi_server):

	app = make_app()
	server = asgi_server(app)
	_, page_id, (_, _, broken, _) = load(server)

	with connect(server, page_id) as ws:
		event(ws, 1, page_id, broken)
		error = receive(ws)
		event(ws, 2, page_id, "event-nope-click")
		unknown = receive(ws)

	assert error == {"type": "result", "ref": 1, "status": 500, "error": "Internal Server Error"}
	assert unknown == {"type": "result", "ref": 2, "status": 404, "error": "Unknown or expired event"}


def test_debug_errors_carry_the_traceback(asgi_server):

	app = make_app()
	app.debug = True
	server = asgi_server(app)
	_, page_id, (_, _, broken, _) = load(server)

	with connect(server, page_id) as ws:
		event(ws, 1, page_id, broken)
		error = receive(ws)

	assert error["error"] == "RuntimeError: broken handler"
	assert "Traceback" in error["traceback"]
	assert error["debug"] is True


def test_unknown_page_is_expired_and_closed(asgi_server):

	server = asgi_server(make_app())

	with connect(server) as ws:
		ws.send(json.dumps({"type": "hello", "page_id": "nope"}))
		assert receive(ws) == {"type": "expired"}
		with pytest.raises(Exception):
			ws.recv(5)
		assert ws.close_code == 1000


def test_handlers_get_a_request_context_from_the_handshake(asgi_server):

	server = asgi_server(make_app())
	_, page_id, (_, _, _, cookie) = load(server)

	with connect(server, page_id, additional_headers={"Cookie": "flavor=mint"}) as ws:
		event(ws, 1, page_id, cookie)
		result = receive(ws)

	assert "Count: mint /" in result["html"]


def test_a_slow_handler_does_not_hold_up_other_pages(asgi_server):

	server = asgi_server(make_app())
	_, slow_page, (_, slow, _, _) = load(server)
	_, quick_page, (increment, *_) = load(server)

	with connect(server, slow_page) as slow_ws, connect(server, quick_page) as quick_ws:
		started = time.monotonic()
		event(slow_ws, 1, slow_page, slow)
		time.sleep(0.05)  # the slow handler is now running

		event(quick_ws, 1, quick_page, increment)
		assert receive(quick_ws)["status"] == 200
		quick = time.monotonic() - started

		assert receive(slow_ws)["status"] == 200
		slow_took = time.monotonic() - started

	# The quick event is answered while the 1 s handler is still running
	assert quick < 0.5
	assert slow_took >= 1


def test_pushes_reach_the_socket(asgi_server):

	counter = Counter()
	server = asgi_server(make_app(counter))
	_, page_id, _ = load(server)

	with connect(server, page_id) as ws:
		counter.count = 5
		threading.Thread(target=counter.refresh).start()
		update = receive(ws)

	assert update["type"] == "update"
	assert update["id"] == counter.id()
	assert update["version"] == 1
	assert "Count: 5" in update["html"]


def test_pushes_made_before_the_socket_drains_them_collapse(asgi_server):

	counter = Counter()
	server = asgi_server(make_app(counter))
	_, page_id, _ = load(server)

	with connect(server, page_id) as ws:
		# Keep the event loop busy while five refreshes are pushed
		server.loop.call_soon_threadsafe(time.sleep, 0.5)
		time.sleep(0.1)
		for count in range(1, 6):
			counter.count = count
			counter.refresh()
		update = receive(ws)

		with pytest.raises(TimeoutError):
			ws.recv(0.3)

	assert "Count: 5" in update["html"]
	assert update["version"] == 5


def test_pushes_wait_for_the_socket(asgi_server):

	counter = Counter()
	app = make_app(counter)
	server = asgi_server(app)
	_, page_id, _ = load(server)

	counter.count = 9
	counter.refresh()

	# Queued while no socket was connected (e.g. while it reconnects), and sent once one is
	with connect(server, page_id) as ws:
		assert "Count: 9" in receive(ws)["html"]


def test_a_new_socket_replaces_the_old_one(asgi_server):

	counter = Counter()
	app = make_app(counter)
	server = asgi_server(app)
	_, page_id, _ = load(server)

	with connect(server, page_id) as old, connect(server, page_id) as new:
		# Closed with a code that tells the browser not to reconnect
		with pytest.raises(Exception):
			old.recv(5)
		assert old.close_code == 4001

		counter.count = 2
		counter.refresh()
		assert "Count: 2" in receive(new)["html"]


def test_closing_the_socket_leaves_nothing_to_wake(asgi_server):

	app = make_app()
	server = asgi_server(app)
	_, page_id, _ = load(server)
	page = app.page_store.pages[page_id]

	with connect(server, page_id):
		assert page.wake is not None

	deadline = time.monotonic() + 5
	while page.wake is not None:
		assert time.monotonic() < deadline
		time.sleep(0.01)


def test_an_open_socket_keeps_its_page_alive_and_expiry_is_sent(asgi_server):

	app = make_app()
	server = asgi_server(app)
	_, page_id, _ = load(server)

	app.config["DOMINO_PAGE_TTL"] = 0.3
	with connect(server, page_id) as ws:
		# Several TTLs; the keepalive (every 0.1 s) touches the page
		with pytest.raises(TimeoutError):
			ws.recv(1)
		assert page_id in app.page_store.pages

		app.page_store.delete(page_id)
		assert receive(ws) == {"type": "expired"}


def test_a_hello_for_another_page_moves_the_socket_and_drops_the_old_page(asgi_server):

	counter = Counter()
	app = make_app(counter)
	server = asgi_server(app)
	_, old, (increment, *_) = load(server)
	_, new, _ = load(server)

	with connect(server, old) as ws:
		# Sent before the hello, so handled on the old page before the socket moves on
		event(ws, 1, old, increment)
		ws.send(json.dumps({"type": "hello", "page_id": new}))
		assert receive(ws)["status"] == 200
		assert receive(ws) == {"type": "ready"}
		assert old not in app.page_store.pages

		# The new page's pushes come down the same socket
		counter.count = 7
		counter.refresh()
		assert "Count: 7" in receive(ws)["html"]


def test_leave_drops_the_page_and_keeps_the_socket(asgi_server):

	app = make_app()
	server = asgi_server(app)
	_, old, _ = load(server)
	_, new, (increment, *_) = load(server)

	with connect(server, old) as ws:
		ws.send(json.dumps({"type": "leave"}))
		# Not told the page expired, though it's gone
		with pytest.raises(TimeoutError):
			ws.recv(0.3)
		assert old not in app.page_store.pages

		ws.send(json.dumps({"type": "hello", "page_id": new}))
		assert receive(ws) == {"type": "ready"}
		event(ws, 1, new, increment)
		assert receive(ws)["status"] == 200


def test_a_second_hello_for_the_same_page_keeps_it(asgi_server):

	app = make_app()
	server = asgi_server(app)
	_, page_id, _ = load(server)

	with connect(server, page_id) as ws:
		ws.send(json.dumps({"type": "hello", "page_id": page_id}))
		assert receive(ws) == {"type": "ready"}

	assert page_id in app.page_store.pages


def test_a_page_swapped_in_brings_its_cookies_to_the_socket(asgi_server):

	server = asgi_server(make_app())
	_, first, _ = load(server)

	# core.js fetches the next page with this header; the browser's cookies changed since the handshake
	request = urllib.request.Request(server.url, headers={"X-Domino-Navigate": "1", "Cookie": "flavor=vanilla"})
	html = urllib.request.urlopen(request).read().decode()
	second = html.split('data-domino-page="')[1].split('"')[0]
	cookie = [part.split('"')[0] for part in html.split('data-event-id="')[1:]][3]

	with connect(server, first, additional_headers={"Cookie": "flavor=mint"}) as ws:
		ws.send(json.dumps({"type": "hello", "page_id": second}))
		assert receive(ws) == {"type": "ready"}
		event(ws, 1, second, cookie)
		assert "Count: vanilla /" in receive(ws)["html"]


def stream(server, page_id):

	connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
	connection.request("GET", f"/_domino/stream?page={page_id}")

	return connection, connection.getresponse()


def test_the_sse_fallback_is_served_without_a_thread(asgi_server):

	counter = Counter()
	app = make_app(counter)
	server = asgi_server(app)
	_, page_id, _ = load(server)
	page = app.page_store.pages[page_id]

	threads = threading.active_count()
	connection, response = stream(server, page_id)
	assert response.status == 200
	assert response.getheader("Content-Type") == "text/event-stream; charset=utf-8"
	assert response.getheader("Cache-Control") == "no-cache"
	assert response.getheader("X-Accel-Buffering") == "no"
	assert response.readline() == b": open\n"
	assert response.readline() == b"\n"
	assert threading.active_count() == threads

	counter.count = 4
	counter.refresh()
	line = response.readline()
	assert line.startswith(b"data: ")
	assert "Count: 4" in json.loads(line[len(b"data: "):])["html"]
	assert response.readline() == b"\n"
	assert response.readline() == b": keepalive\n"

	# Stops when the client goes away, instead of writing into the void
	connection.close()
	deadline = time.monotonic() + 5
	while page.wake is not None:
		assert time.monotonic() < deadline
		time.sleep(0.01)


def test_the_sse_fallback_404s_for_unknown_pages(asgi_server):

	server = asgi_server(make_app())

	connection, response = stream(server, "nope")
	assert response.status == 404
	assert json.loads(response.read()) == {"error": "Unknown or expired page"}
	connection.close()


def test_other_requests_reach_flask(asgi_server):

	server = asgi_server(make_app())

	html = urllib.request.urlopen(server.url + "plain").read().decode()
	assert "static" in html
	assert urllib.request.urlopen(server.url + "_domino/core").read().startswith(b"window.Domino")


class Visits(t.div):


	def render(self):

		from flask import session

		return [
			t.p() [f"Visits: {session.get('visits', 0)}"],
			t.button(on_click=self.visit) ["visit"],
			t.button(on_click=self.look) ["look"],
			t.button(on_click=self.forget) ["forget"],
		]


	def visit(self):

		from flask import session

		session["visits"] = session.get("visits", 0) + 1


	def look(self):

		pass


	def forget(self):

		from flask import session

		session.clear()


def session_app():

	app = Domino(__name__)
	app.secret_key = "test"

	@app.route("/")
	def index():
		return Document() [Visits()]

	return app


def test_session_changes_over_the_socket_reach_the_browser_with_a_one_time_token(asgi_server):

	server = asgi_server(session_app())
	_, page_id, (visit, look, _) = load(server)

	with connect(server, page_id) as ws:
		event(ws, 1, page_id, visit)
		first = receive(ws)
		event(ws, 2, page_id, look)
		unchanged = receive(ws)
		event(ws, 3, page_id, visit)
		second = receive(ws)

	# Later events on the same socket see the changed session
	assert "Visits: 1" in first["html"] and "Visits: 2" in second["html"]
	assert "session" in first and "session" not in unchanged

	# The page exchanges the token for the cookie, once
	connection = http.client.HTTPConnection("127.0.0.1", server.port)
	connection.request("POST", f"/_domino/session/{second['session']}", headers={"X-Domino-Page": page_id})
	response = connection.getresponse()
	response.read()
	assert response.status == 204
	cookie = response.getheader("Set-Cookie")
	assert cookie.startswith("session=") and "HttpOnly" in cookie

	connection.request("POST", f"/_domino/session/{second['session']}", headers={"X-Domino-Page": page_id})
	again = connection.getresponse()
	again.read()
	assert again.status == 404

	# A new page load with that cookie has the session
	request = urllib.request.Request(server.url, headers={"Cookie": cookie.split(";")[0]})
	assert "Visits: 2" in urllib.request.urlopen(request).read().decode()


def test_clearing_the_session_over_the_socket_deletes_the_cookie(asgi_server):

	app = session_app()

	@app.route("/remember")
	def remember():
		from flask import session
		session.permanent = True  # refreshed on every request, like an accounts login
		session["visits"] = 5
		return "ok"

	server = asgi_server(app)
	cookie = urllib.request.urlopen(server.url + "remember").headers["Set-Cookie"].split(";")[0]

	request = urllib.request.Request(server.url, headers={"Cookie": cookie})
	html = urllib.request.urlopen(request).read().decode()
	page_id = html.split('data-domino-page="')[1].split('"')[0]
	forget = [part.split('"')[0] for part in html.split('data-event-id="')[1:]][2]

	with connect(server, page_id, additional_headers={"Cookie": cookie}) as ws:
		event(ws, 1, page_id, forget)
		result = receive(ws)

	# The browser still sends its old cookie with the hand-off; only the deletion comes back
	connection = http.client.HTTPConnection("127.0.0.1", server.port)
	connection.request("POST", f"/_domino/session/{result['session']}", headers={"Cookie": cookie, "X-Domino-Page": page_id})
	response = connection.getresponse()
	response.read()
	cookies = response.msg.get_all("Set-Cookie")

	assert len(cookies) == 1
	assert cookies[0].startswith("session=;") and "Max-Age=0" in cookies[0]


def test_sockets_from_other_sites_are_refused(asgi_server):

	server = asgi_server(make_app())
	_, page_id, _ = load(server)

	with pytest.raises(Exception):
		with connect(server, page_id, additional_headers={"Origin": "http://evil.example"}):
			pass

	with connect(server, page_id, additional_headers={"Origin": f"http://127.0.0.1:{server.port}"}) as ws:
		assert ws is not None


def test_with_cookies_applies_set_cookie_headers():

	from domino.asgi import with_cookies

	header = "flavor=mint; session=old"

	assert with_cookies(header, ["session=new; HttpOnly; Path=/"]) == "flavor=mint; session=new"
	assert with_cookies(header, ["session=; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; Path=/"]) == "flavor=mint"
