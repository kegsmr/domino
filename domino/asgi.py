"""Serving a Domino app over ASGI, e.g. `uvicorn myapp:app.asgi`.

Each tab opens one WebSocket at /_domino/ws, which carries its events up and their results and
pushed updates down, so an idle tab costs a coroutine instead of a thread. /_domino/stream (the
Server-Sent Events fallback) is served here too, without a thread. Every other request goes to
the Flask app, as WSGI, in a thread pool.
"""

import asyncio
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from a2wsgi import WSGIMiddleware
from werkzeug.test import EnvironBuilder

from .core import DEFAULT_PAGE


WS_PATH = "/_domino/ws"
STREAM_PATH = "/_domino/stream"

# "path/to/app.py:attribute", for the processes uvicorn's reloader starts
ENV_APP = "DOMINO_ASGI_APP"

# Sent when a newer socket for the same page took over, so the browser doesn't reconnect
CLOSE_REPLACED = 4001

log = logging.getLogger(__name__)


class ASGIApp:
	"""A Domino app as an ASGI application. Use `app.asgi` rather than making one."""


	def __init__(self, app):

		self.app = app

		workers = int(app.config["DOMINO_WORKERS"])

		# Page loads and other Flask requests
		self.wsgi = WSGIMiddleware(self.mark_request, workers=workers)

		# Event handlers are sync Python, so they run here and the event loop never waits on
		# one. A pool of its own, so slow page loads can't hold up events (or the other way)
		self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="domino-event")


	async def __call__(self, scope, receive, send):

		path = scope.get("path")

		if scope["type"] == "websocket" and path == WS_PATH and self.app.config["DOMINO_WEBSOCKET"]:
			await Connection(self, scope, receive, send).run()
		elif scope["type"] == "http" and path == STREAM_PATH:
			await self.stream(scope, receive, send)
		else:
			# a2wsgi refuses other WebSockets and answers lifespan messages
			await self.wsgi(scope, receive, send)


	def mark_request(self, environ, start_response):

		# Lets the route wrapper tell the browser that this server has the WebSocket
		environ["domino.websocket"] = bool(self.app.config["DOMINO_WEBSOCKET"])

		return self.app(environ, start_response)


	def run_event(self, environ, page_id, message):
		"""Handle one event from a WebSocket, like the POST endpoint does. Runs in a worker thread."""

		# A request context built from the socket's handshake, so handlers can still use
		# url_for, request.cookies and session
		with self.app.request_context(dict(environ)) as context:
			page = self.app._get_page(page_id) or DEFAULT_PAGE
			payload, status = self.app.handle_event(page, message.get("event_id"), message.get("data"))

			# A socket can't set cookies: the browser fetches a changed session with a token
			token, cookies = self.app.session_handoff(context.session)
			if token:
				payload = dict(payload, session=token)
				# and this socket's later events see the new session
				environ["HTTP_COOKIE"] = with_cookies(environ.get("HTTP_COOKIE", ""), cookies)

		return payload, status


	async def stream(self, scope, receive, send):

		query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
		page = self.app._get_page((query.get("page") or [None])[0])

		if page is None:
			body = json.dumps({"error": "Unknown or expired page"}).encode()
			await send({"type": "http.response.start", "status": 404, "headers": [(b"content-type", b"application/json")]})
			await send({"type": "http.response.body", "body": body})
			return

		await send({"type": "http.response.start", "status": 200, "headers": [
			(b"content-type", b"text/event-stream; charset=utf-8"),
			(b"cache-control", b"no-cache"),
			(b"x-accel-buffering", b"no"),
		]})
		await send({"type": "http.response.body", "body": b": open\n\n", "more_body": True})

		subscription = Subscription(self.app, page)
		disconnected = asyncio.ensure_future(wait_for_disconnect(receive))
		# Writes to a closed connection don't fail here, so stop as soon as the client goes
		disconnected.add_done_callback(lambda _: subscription.ready.set())

		try:
			while not disconnected.done():
				updates = await subscription.next(self.app.config["DOMINO_KEEPALIVE"])
				if updates is None or disconnected.done():
					break
				chunk = "".join(f"data: {json.dumps(update)}\n\n" for update in updates) or ": keepalive\n\n"
				await send({"type": "http.response.body", "body": chunk.encode(), "more_body": True})
			if not disconnected.done():
				await send({"type": "http.response.body", "body": b""})
		finally:
			disconnected.cancel()
			subscription.close()


async def wait_for_disconnect(receive):

	while True:
		message = await receive()
		if message["type"] == "http.disconnect":
			return


def waker(loop, event):
	"""A callback any thread can call to set `event` in `loop`."""

	def wake():

		try:
			loop.call_soon_threadsafe(event.set)
		except RuntimeError:
			# The loop has closed, and the connection with it
			pass

	return wake


class Subscription:
	"""The updates pushed to one page, for a connection in this event loop. The newest
	subscription (or threaded stream) for a page takes its updates; older ones end."""


	def __init__(self, app, page):

		self.app = app
		self.page = page
		self.expired = False
		self.ready = asyncio.Event()
		self.stream = page.open_stream(waker(asyncio.get_running_loop(), self.ready))


	async def next(self, timeout):
		"""The updates pushed since the last call, after waiting up to `timeout` seconds for one
		(so maybe none), or None once a newer stream has replaced this one or the page expired."""

		try:
			await asyncio.wait_for(self.ready.wait(), timeout)
		except asyncio.TimeoutError:
			pass
		self.ready.clear()

		# Loading touches the page, so an open connection keeps it alive; stop if it's gone
		# anyway (expired, or pushed out by DOMINO_MAX_PAGES)
		if self.app._get_page(self.page.id) is None:
			self.expired = True
			return None

		# Doesn't wait: updates are already queued, and the lock is only held briefly
		return self.page.pull(self.stream, 0)


	def close(self):

		self.page.close_stream(self.stream)


class Connection:
	"""One tab's WebSocket. JSON messages; the browser sends
		{"type": "hello", "page_id"} first, then {"type": "event", "ref", "page_id", "event_id", "data"},
	and receives
		{"type": "ready"} once bound to the page, or {"type": "expired"} if it's unknown,
		{"type": "result", "ref", "status", ...} with what POST /_domino/events would answer,
		{"type": "update", "id", "html", "version"} for each pushed update, as over SSE.
	"""


	def __init__(self, asgi, scope, receive, send):

		self.asgi = asgi
		self.app = asgi.app
		self.scope = scope
		self.receive = receive
		self.raw_send = send
		self.environ = handshake_environ(scope)
		self.page_id = None
		self.closed = False
		self.events = asyncio.Queue()


	async def run(self):

		message = await self.receive()
		if message["type"] != "websocket.connect":
			return

		# Another site's page could otherwise open a socket with this visitor's cookies
		if not same_origin(self.scope):
			await self.raw_send({"type": "websocket.close", "code": 1008})
			return

		await self.raw_send({"type": "websocket.accept"})

		tasks = [asyncio.ensure_future(self.handle_events())]
		try:
			while not self.closed:
				message = await self.receive()
				if message["type"] == "websocket.disconnect":
					break
				data = parse(message)
				if data.get("type") == "event":
					self.events.put_nowait(data)
				elif data.get("type") == "hello" and self.page_id is None:
					tasks.append(asyncio.ensure_future(self.hello(data.get("page_id"))))
		finally:
			self.closed = True
			for task in tasks:
				task.cancel()


	async def hello(self, page_id):

		page = None
		if isinstance(page_id, str):
			page = self.app._get_page(page_id)
		if page is None:
			await self.send({"type": "expired"})
			await self.close(1000)
			return

		self.page_id = page.id
		subscription = Subscription(self.app, page)
		try:
			await self.send({"type": "ready"})
			while not self.closed:
				updates = await subscription.next(self.app.config["DOMINO_KEEPALIVE"])
				if updates is None:
					break
				for update in updates:
					await self.send(dict(update, type="update"))
			if subscription.expired:
				await self.send({"type": "expired"})
				await self.close(1000)
			else:
				await self.close(CLOSE_REPLACED)
		finally:
			subscription.close()


	async def handle_events(self):

		# One at a time, in the order sent: they'd wait for the page's lock anyway, and this
		# way a later event can't overtake an earlier one
		loop = asyncio.get_running_loop()
		while True:
			message = await self.events.get()
			page_id = self.page_id or message.get("page_id")
			try:
				payload, status = await loop.run_in_executor(self.asgi.executor, self.asgi.run_event, self.environ, page_id, message)
			except Exception:
				log.exception("Domino event %s failed", message.get("event_id"))
				payload, status = {"error": "Internal Server Error"}, 500
			await self.send(dict(payload, type="result", ref=message.get("ref"), status=status))


	async def send(self, data):

		if self.closed:
			return

		try:
			await self.raw_send({"type": "websocket.send", "text": json.dumps(data)})
		except (OSError, RuntimeError):
			# The client went away; the receive loop sees the disconnect and stops
			self.closed = True


	async def close(self, code):

		if self.closed:
			return
		self.closed = True

		try:
			await self.raw_send({"type": "websocket.close", "code": code})
		except (OSError, RuntimeError):
			pass


def with_cookies(header, set_cookies):
	"""A Cookie request header updated with Set-Cookie response headers (expired ones removed)."""

	from http.cookies import SimpleCookie

	jar = SimpleCookie()
	jar.load(header or "")
	cookies = {name: morsel.value for name, morsel in jar.items()}

	for set_cookie in set_cookies:
		parsed = SimpleCookie()
		parsed.load(set_cookie)
		for name, morsel in parsed.items():
			if morsel["max-age"] == "0" or not morsel.value or "1970" in morsel["expires"]:
				cookies.pop(name, None)
			else:
				cookies[name] = morsel.value

	return "; ".join(f"{name}={value}" for name, value in cookies.items())


def same_origin(scope):
	"""Whether a WebSocket handshake comes from a page of this site. Browsers send Origin on
	every WebSocket handshake but don't apply CORS to them, so this is checked here."""

	headers = dict((name.decode("latin-1").lower(), value.decode("latin-1")) for name, value in scope.get("headers", []))
	origin = headers.get("origin")

	# Not a browser (tests, scripts): nothing to protect
	if origin is None:
		return True

	return urlsplit(origin).netloc.lower() == headers.get("host", "").lower()


def parse(message):

	try:
		data = json.loads(message.get("text") or message.get("bytes") or "")
	except ValueError:
		return {}

	if not isinstance(data, dict):
		return {}

	return data


def handshake_environ(scope):
	"""A WSGI environ for the WebSocket's handshake request, for handlers' request context."""

	headers = [(name.decode("latin-1"), value.decode("latin-1")) for name, value in scope.get("headers", [])]
	host = dict((name.lower(), value) for name, value in headers).get("host", "localhost")

	scheme = "http"
	if scope.get("scheme") in ("https", "wss"):
		scheme = "https"

	environ_base = {}
	if scope.get("client"):
		environ_base["REMOTE_ADDR"] = scope["client"][0]

	builder = EnvironBuilder(
		path=WS_PATH,
		base_url=f"{scheme}://{host}{scope.get('root_path', '')}",
		headers=headers,
		environ_base=environ_base,
	)
	try:
		return builder.get_environ()
	finally:
		builder.close()


def app_location(app):
	"""Where an app defined at the top level of a module file is, as "path/to/app.py:attribute",
	or the folder of one `domino run` made for a folder with just pages/."""

	folder = getattr(app, "domino_folder", None)
	if folder:
		return folder

	module = sys.modules.get(app.import_name)
	path = getattr(module, "__file__", None)
	if not path:
		return None

	for name, value in vars(module).items():
		if value is app:
			return f"{Path(path).resolve()}:{name}"

	return None


def serve(app, host="127.0.0.1", port=5000, reload=False, **options):
	"""Serve `app` with uvicorn. With reload, uvicorn restarts a new process when a file in the
	app's folder changes; that process finds the app through from_environ()."""

	import uvicorn

	target = app.asgi
	location = None
	if reload:
		location = app_location(app)
		if location is None:
			log.warning("Domino: not reloading on changes; the app must be defined at the top level of a module file")

	if location is not None:
		os.environ[ENV_APP] = location
		# The new process creates the app again, and reads FLASK_DEBUG when it does
		if app.debug:
			os.environ["FLASK_DEBUG"] = "1"
		target = "domino.asgi:from_environ"
		options.update(factory=True, reload=True, reload_dirs=[app.root_path])

	# Server-Sent Event streams only end when their client goes, so don't wait for them
	# forever when stopping (or restarting on a change)
	options.setdefault("timeout_graceful_shutdown", 3)

	uvicorn.run(target, host=host, port=port, **options)


def from_environ():
	"""The app named by DOMINO_ASGI_APP, as ASGI. uvicorn's reloader calls this in each new process."""

	from .cli import load_app, load_module

	location = os.environ[ENV_APP]
	if os.path.isdir(location):
		return load_app(location).asgi

	path, _, name = location.rpartition(":")

	# For `python app.py`, the new process has already run app.py as its main module;
	# loading it again would make a second app (and start its threads twice)
	module = sys.modules.get("__main__")
	main_path = getattr(module, "__file__", None)
	if not main_path or Path(main_path).resolve() != Path(path):
		module = load_module(path)

	return getattr(module, name).asgi
