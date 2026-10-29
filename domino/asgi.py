"""Serving a Domino app over ASGI, e.g. `uvicorn myapp:app.asgi`.

Each tab opens one WebSocket at /_domino/ws, which carries its events up and their results and
pushed updates down, so an idle tab costs a coroutine instead of a thread. /_domino/stream (the
Server-Sent Events fallback) is served here too, without a thread, as is /_domino/tailwind/watch
while debugging (see domino.tailwind). Every other request goes to
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

from . import tailwind
from .core import DEFAULT_PAGE, max_event_bytes
from .patches import Patcher


WS_PATH = "/_domino/ws"
STREAM_PATH = "/_domino/stream"

# "path/to/app.py:attribute", for the processes uvicorn's reloader starts
ENV_APP = "DOMINO_ASGI_APP"

# "1" when those processes hot reload changed files themselves (see domino.hot)
ENV_HOT = "DOMINO_ASGI_HOT"

# Sent when a newer socket for the same page took over, so the browser doesn't reconnect
CLOSE_REPLACED = 4001

# A message bigger than DOMINO_MAX_EVENT_MB, or too many waiting to be handled
CLOSE_TOO_BIG = 1009
CLOSE_POLICY = 1008

# Messages a socket may have waiting for the ones before them to be handled
MAX_QUEUED = 100

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

		# Made once in the process that serves, so a debug server warns here, once
		if app.debug:
			from .devtools import startup_warnings
			startup_warnings(app)


	async def __call__(self, scope, receive, send):

		path = scope.get("path")

		if scope["type"] == "websocket" and path == WS_PATH and self.app.config["DOMINO_WEBSOCKET"]:
			await Connection(self, scope, receive, send).run()
		elif scope["type"] == "http" and path == STREAM_PATH:
			await self.stream(scope, receive, send)
		elif path == tailwind.WATCH_URL and self.app.tailwind and self.app.debug:
			await tailwind.serve_watch(self.app, scope, receive, send)
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
			# An event from a hidden tab (which said so) means it's being used: catch up first
			if page.paused:
				page.resume()
			payload, status = self.app.handle_event(page, message.get("event_id"), message.get("data"))

			# A socket can't set cookies: the browser fetches a changed session with a token
			token, cookies = self.app.session_handoff(context.session, page)
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
		# Pauses are told over the WebSocket; this page is back without one, so catch up
		if page.paused:
			await asyncio.get_running_loop().run_in_executor(self.executor, page.resume)
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
		self.left = False  # the socket moved on to another page (see Connection.leave)
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
		{"type": "hello", "page_id", "patch": true} first, then {"type": "event", "ref", "page_id", "event_id", "data"},
		and when it swaps in another page without reloading (see navigate() in core.js), a new
		{"type": "hello", "page_id", "patch": true}, or {"type": "leave"} if that page needs nothing from the server,
		{"type": "pause"} when the tab is hidden and {"type": "resume"} when it's shown again,
		{"type": "resend", "id"} if it can't apply a patch,
	and receives
		{"type": "ready"} once bound to the page, or {"type": "expired"} if it's unknown,
		{"type": "result", "ref", "status", ...} with what POST /_domino/events would answer,
		{"type": "update", "id", "html", "version"} for each pushed update, as over SSE.
	With "patch" in the hello, a result or update may carry "patch" (see domino.patches) instead
	of "html", and "base": the version of the last HTML this socket sent for that component.
	"""


	def __init__(self, asgi, scope, receive, send):

		self.asgi = asgi
		self.app = asgi.app
		self.scope = scope
		self.receive = receive
		self.raw_send = send
		self.environ = handshake_environ(scope)
		self.page_id = None
		self.subscription = None  # to the page it's bound to
		self.listening = None  # the task sending that page's pushes
		self.closed = False
		self.events = asyncio.Queue(MAX_QUEUED)
		self.max_message = max_event_bytes(self.app)
		self.patcher = None  # what this socket sent, if the browser takes patches
		self.sending = asyncio.Lock()  # messages are encoded in the order they're sent


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
				# Events are small; a bigger message (DOMINO_MAX_EVENT_MB) ends the socket
				if len(message.get("text") or message.get("bytes") or "") > self.max_message:
					await self.close(CLOSE_TOO_BIG)
					break
				data = parse(message)
				# Hellos go in line with events, so a page's last events reach it before the
				# socket moves on to the next page
				if data.get("type") in ("event", "hello", "leave", "pause", "resume"):
					try:
						self.events.put_nowait(data)
					except asyncio.QueueFull:
						# Far more than a tab sends while its events are handled: a flood
						await self.close(CLOSE_POLICY)
						break
				elif data.get("type") == "resend":
					tasks = [task for task in tasks if not task.done()]
					if len(tasks) <= MAX_QUEUED:
						tasks.append(asyncio.ensure_future(self.resend(data.get("id"))))
		finally:
			self.closed = True
			# The page stays until it expires or a new socket takes it (whose hello resumes it);
			# paused meanwhile, so changes to what it shows aren't rendered for nobody
			if self.subscription is not None:
				self.subscription.page.pause_for(self.subscription.stream)
			for task in tasks:
				task.cancel()
			if self.listening is not None:
				self.listening.cancel()


	async def hello(self, page_id, patch=False):
		"""Bind the socket to a page: the tab's first, or one it swapped in without reloading.
		`patch`: the browser takes patches (core.js does; a tab with an older one doesn't)."""

		if page_id is not None and page_id == self.page_id:
			await self.send({"type": "ready"})
			return

		self.leave()

		page = None
		if isinstance(page_id, str):
			page = self.app._get_page(page_id)
		if page is None:
			await self.send({"type": "expired"})
			await self.close(1000)
			return

		# Loaded after the socket's handshake, maybe with newer cookies
		if page.cookie is not None:
			self.environ["HTTP_COOKIE"] = page.cookie

		# Patches start from what this socket sent for the page; the browser forgets the rest too
		self.patcher = Patcher() if patch and self.app.config["DOMINO_PATCHES"] else None

		self.page_id = page.id
		self.subscription = Subscription(self.app, page)

		# A socket that went (or whose tab was hidden) left it paused. Resumed once this socket's
		# stream is the page's, so the old socket can't pause it again after this
		if page.paused:
			await asyncio.get_running_loop().run_in_executor(self.asgi.executor, page.resume)

		self.listening = asyncio.ensure_future(self.listen(self.subscription))


	def leave(self):
		"""Stop sending the bound page's pushes. The tab has moved on to another page, so the page
		is dropped too, unless another socket (a duplicated tab) has taken it over."""

		subscription = self.subscription
		if subscription is None:
			return
		self.subscription = self.listening = self.page_id = None

		# Not cancelled, which could cut a message short: woken, it sees it should stop
		subscription.left = True
		subscription.ready.set()
		subscription.close()

		if subscription.page.stream is subscription.stream:
			self.app._drop_page(subscription.page)


	async def listen(self, subscription):

		try:
			await self.send({"type": "ready"})
			while not self.closed and not subscription.left:
				updates = await subscription.next(self.app.config["DOMINO_KEEPALIVE"])
				if updates is None or subscription.left:
					break
				for update in updates:
					# Other messages (see Page.notify) have a type of their own
					await self.send(dict(update, type=update.get("type", "update")))
			if subscription.left:
				return
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
			if message.get("type") == "hello":
				await self.hello(message.get("page_id"), message.get("patch") is True)
				continue
			if message.get("type") in ("pause", "resume"):
				await self.visibility(message["type"] == "pause")
				continue
			if message.get("type") == "leave":
				self.leave()
				continue
			page_id = self.page_id or message.get("page_id")
			try:
				payload, status = await loop.run_in_executor(self.asgi.executor, self.asgi.run_event, self.environ, page_id, message)
			except Exception:
				log.exception("Domino event %s failed", message.get("event_id"))
				payload, status = {"error": "Internal Server Error"}, 500
			await self.send(dict(payload, type="result", ref=message.get("ref"), status=status))


	async def visibility(self, hidden):
		"""The tab was hidden (pause the bound page) or shown again (send what changed meanwhile)."""

		if self.subscription is None:
			return

		page = self.subscription.page
		if hidden:
			page.pause()
		elif page.paused:
			await asyncio.get_running_loop().run_in_executor(self.asgi.executor, page.resume)


	async def resend(self, element_id):

		if self.patcher is None or not isinstance(element_id, str):
			return

		async with self.sending:
			message = self.patcher.resend(element_id)
			if message is not None:
				await self.send_now(message)


	async def send(self, data):

		async with self.sending:
			if self.patcher is not None:
				data = self.patcher.encode(data)
			await self.send_now(data)


	async def send_now(self, data):

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
	except (ValueError, RecursionError):
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
	"""Serve `app` with uvicorn. With reload, a new process serves it, which finds the app through
	from_environ(): it hot reloads changed files itself and is restarted for changes it can't swap
	in (see domino.hot), or, with {"domino": {"hot_reload": false}}, uvicorn restarts it whenever a
	file in the app's folder changes."""

	import uvicorn

	from . import hot

	target = app.asgi
	location = None
	if reload:
		location = app_location(app)
		if location is None:
			log.warning("Domino: not reloading on changes; the app must be defined at the top level of a module file")

	# Server-Sent Event streams only end when their client goes, so don't wait for them
	# forever when stopping (or restarting on a change)
	options.setdefault("timeout_graceful_shutdown", 3)

	os.environ.pop(ENV_HOT, None)

	# Server-Sent Event streams only end when their client goes, so don't wait for them
	# forever when stopping (or restarting on a change)
	options.setdefault("timeout_graceful_shutdown", 3)
	# {"domino": {"ws_compression": false}} saves the ~40 KB per socket deflate keeps
	options.setdefault("ws_per_message_deflate", bool(app.config["DOMINO_WS_COMPRESSION"]))

	if location is not None:
		os.environ[ENV_APP] = location
		# The new process creates the app again, and reads FLASK_DEBUG when it does
		if app.debug:
			os.environ["FLASK_DEBUG"] = "1"
		target = "domino.asgi:from_environ"
		if app.config["DOMINO_HOT_RELOAD"]:
			os.environ[ENV_HOT] = "1"
			hot.serve(target, app.root_path, host=host, port=port, **options)
			return
		options.update(factory=True, reload=True, reload_dirs=[app.root_path])

	uvicorn.run(target, host=host, port=port, **options)


def from_environ():
	"""The app named by DOMINO_ASGI_APP, as ASGI. uvicorn's reloader calls this in each new process."""

	from .cli import load_app, load_module

	location = os.environ[ENV_APP]
	path = None
	if os.path.isdir(location):
		app = load_app(location)
	else:
		path, _, name = location.rpartition(":")

		# For `python app.py`, the new process has already run app.py as its main module;
		# loading it again would make a second app (and start its threads twice)
		module = sys.modules.get("__main__")
		main_path = getattr(module, "__file__", None)
		if not main_path or Path(main_path).resolve() != Path(path):
			module = load_module(path)
		app = getattr(module, name)

	# Changed files are swapped in by this process while it serves (see domino.hot)
	if os.environ.get(ENV_HOT) == "1":
		from .hot import HotReloader
		HotReloader(app, path).start()

	return app.asgi
