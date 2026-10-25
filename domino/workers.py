"""`domino serve --workers N`: one app on every CPU core, with nothing to configure.

N worker processes each serve the app (app.asgi, with uvicorn) on a socket of their own on
127.0.0.1, and this process listens on the public port and passes each request on to one of
them. A page lives in the memory of the worker that rendered it, so requests about a page must
reach that worker. Every page id and session token starts with its worker's id ("w3-...", see
core.worker_prefix), and the rule is:

	a request under /_domino/ goes to the worker named by the page id or token it carries: its
	`page` query parameter (the WebSocket, the Server-Sent Events stream), the last part of its
	path (/_domino/session/<token>), its X-Domino-Page header (uploads) or a POSTed event's JSON
	`page_id`. Everything else (page
	loads, static files, other routes) goes to the worker with the fewest requests waiting
	for an answer, preferring the one the connection's last such request went to.

So no sticky sessions are needed. The router doesn't parse responses: browsers send a
connection's next request only once the response to the last one has arrived, so it just copies
each response back, and a WebSocket's (or a chunked upload's) connection becomes a plain pipe to
its worker.
"""

import asyncio
import ipaddress
import itertools
import json
import multiprocessing
import multiprocessing.connection
import os
import re
import signal
import socket
import sys
import threading
import time
from urllib.parse import parse_qs, unquote

from .core import WORKER_ID_ENV


# Requests longer than this before their body are refused (uvicorn and nginx allow less or about as much)
MAX_HEAD = 64 * 1024

# Event bodies read to find their page_id
MAX_PEEK = 1024 * 1024

CHUNK = 64 * 1024

# A worker that exits sooner than this after starting is restarted after a growing delay
STEADY = 5
MAX_DELAY = 10

# Seconds workers get to finish their requests when stopping (open streams never do)
GRACEFUL = 3

WORKER_HINT = re.compile(r"w(\d+)-")


def default_count():
	"""The number of CPU cores this process may use."""

	try:
		return max(1, len(os.sched_getaffinity(0)))
	except AttributeError:
		return max(1, os.cpu_count() or 1)


def log(message):

	print(f"domino: {message}", file=sys.stderr, flush=True)


def serve(location, host="127.0.0.1", port=8000, workers=None):
	"""Serve the app at `location` (its folder, its file, or "path/to/app.py:attribute") with
	`workers` processes behind a router on host:port. Returns the exit status."""

	supervisor = Supervisor(location, host, port, workers or default_count())

	try:
		return run_loop(supervisor.run())
	except KeyboardInterrupt:
		# Where signals can't be handled in the event loop (Windows)
		return 0
	finally:
		supervisor.stop_workers()


def run_loop(coroutine):

	# uvloop (installed with uvicorn[standard]) makes copying bytes cheaper; run() is 0.18+
	try:
		from uvloop import run
	except ImportError:
		run = asyncio.run

	return run(coroutine)


# The router


def worker_of(value):
	"""The worker id a page id or session token starts with, or None."""

	match = WORKER_HINT.match(value or "")

	return int(match.group(1)) if match else None


def worker_hint(path, query):
	"""The worker a request under /_domino/ belongs to, from its URL, or None."""

	page = parse_qs(query).get("page")
	if page and worker_of(page[0]):
		return worker_of(page[0])

	return worker_of(unquote(path.rsplit("/", 1)[-1]))


def body_hint(body):
	"""The worker of a POSTed event's page, from its JSON body."""

	try:
		data = json.loads(body)
	except ValueError:
		return None

	if not isinstance(data, dict) or not isinstance(data.get("page_id"), str):
		return None

	return worker_of(data["page_id"])


def trusted_hosts():
	"""Clients whose X-Forwarded-* headers are kept, as uvicorn decides: FORWARDED_ALLOW_IPS,
	addresses or networks ("10.0.0.0/8")."""

	value = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")

	return {host.strip() for host in value.split(",") if host.strip()}


def is_trusted(client, trusted):
	"""Whether `client` is one of the `trusted` addresses or in one of its networks."""

	if "*" in trusted or client in trusted:
		return True

	try:
		address = ipaddress.ip_address(client or "")
	except ValueError:
		return False

	for entry in trusted:
		if "/" not in entry:
			continue
		try:
			if address in ipaddress.ip_network(entry, strict=False):
				return True
		except ValueError:
			continue

	return False


def forward_head(lines, client, trusted, connection=None):
	"""The request's head for a worker: the client's address added to X-Forwarded-For, which
	the workers trust since the router connects from 127.0.0.1. A client that isn't a trusted
	proxy can't pass its own X-Forwarded-* headers on, just as without the router.

	`connection`, if given, replaces the request's Connection and Upgrade headers: b"close" for
	a connection the router pipes from then on (it reads no more requests on it, so one sent
	after this would reach the worker unchecked, X-Forwarded-For and all), b"Upgrade, close"
	for a WebSocket, b"" to drop an upgrade to anything else."""

	trust = is_trusted(client, trusted)
	forwarded = []
	out = [lines[0]]

	for line in lines[1:]:
		name = line.split(b":", 1)[0].strip().lower()
		if name in (b"x-forwarded-for", b"x-forwarded-proto", b"x-forwarded-host"):
			if not trust:
				continue
			if name == b"x-forwarded-for":
				forwarded.append(line.split(b":", 1)[1].strip())
				continue
		if connection is not None and name in (b"connection", b"upgrade"):
			continue
		out.append(line)

	if client:
		forwarded.append(client.encode("latin-1"))
	if forwarded:
		out.append(b"X-Forwarded-For: " + b", ".join(forwarded))
	if connection:
		out.append(b"Connection: " + connection)
		if b"upgrade" in connection.lower():
			out.append(b"Upgrade: websocket")

	return b"\r\n".join(out) + b"\r\n\r\n"


def tokens(value):
	"""The comma-separated tokens of a header like Connection, lowercased."""

	return {token.strip().lower() for token in value.split(",") if token.strip()}


class Router:
	"""Accepts the public connections and passes each request on to a worker."""


	def __init__(self, ports):

		self.ports = ports  # worker id -> its port on 127.0.0.1
		self.waiting = dict.fromkeys(ports, 0)  # worker id -> requests it hasn't started answering
		self.turn = itertools.cycle(sorted(ports))
		self.trusted = trusted_hosts()
		self.connections = set()


	def pick(self, hint, last=None):
		"""The worker for a request: the one its page id names, or else the least busy one.
		Ties go to `last`, the worker of the connection's last request, so a page and its
		scripts load from one, and otherwise to each worker in turn."""

		if hint in self.ports:
			return hint

		least = min(self.waiting.values())
		if last is not None and self.waiting[last] == least:
			return last

		for _ in self.ports:
			worker = next(self.turn)
			if self.waiting[worker] == least:
				return worker


	async def handle(self, reader, writer):

		connection = Proxy(self, reader, writer)
		task = asyncio.current_task()
		self.connections.add(task)
		try:
			await connection.run()
		finally:
			self.connections.discard(task)


class Upstream:
	"""A connection to a worker, kept for the client connection's later requests to it."""


	def __init__(self, worker, reader, writer):

		self.worker = worker
		self.reader = reader
		self.writer = writer
		self.pump = None
		self.waiting = 0  # requests sent that no response has started for


	def alive(self):

		return not self.pump.done() and not self.writer.is_closing()


class Proxy:
	"""One client connection."""


	def __init__(self, router, reader, writer):

		self.router = router
		self.reader = reader
		self.writer = writer
		peer = writer.get_extra_info("peername")
		self.client = peer[0] if isinstance(peer, tuple) else None
		self.upstreams = {}  # worker id -> Upstream
		self.active = None  # the Upstream answering the latest request
		self.last = None  # the worker of the latest request without a page id


	async def run(self):

		try:
			while True:
				try:
					head = await self.reader.readuntil(b"\r\n\r\n")
				except asyncio.IncompleteReadError:
					break
				except asyncio.LimitOverrunError:
					await self.refuse(431, "Request Header Fields Too Large")
					break
				if not await self.forward(head):
					break
		except (OSError, asyncio.IncompleteReadError):
			pass
		finally:
			await self.finish()


	async def forward(self, head):
		"""Send one request to its worker. False once the connection has no more requests."""

		lines = head[:-4].split(b"\r\n")
		try:
			method, target, _ = lines[0].decode("latin-1").split(" ", 2)
			headers = {}
			for line in lines:
				# The router and the worker must read the head alike, or a header only the worker
				# sees (after a bare \n, say) could make it read the body as another request
				if b"\r" in line or b"\n" in line or b"\0" in line or line[:1] in (b" ", b"\t"):
					raise ValueError("Malformed header line")
			for line in lines[1:]:
				name, value = line.decode("latin-1").split(":", 1)
				if not name or name != name.strip():
					raise ValueError("Malformed header name")
				name, value = name.lower(), value.strip()
				# Two lengths would let the router and the worker disagree on where the body ends
				if name == "content-length" and headers.get(name, value) != value:
					raise ValueError("Conflicting Content-Length headers")
				headers[name] = value
			length = headers.get("content-length", "0")
			if not length.isdigit() or not length.isascii():
				raise ValueError("Invalid Content-Length")
			length = int(length)
			# Both: which one the worker goes by is up to it (RFC 9112 says reject it)
			if "content-length" in headers and "transfer-encoding" in headers:
				raise ValueError("Content-Length and Transfer-Encoding")
		except ValueError:
			await self.refuse(400, "Bad Request")
			return False

		chunked = "transfer-encoding" in headers
		# Only a WebSocket is piped as an upgrade; other upgrades are dropped and the request is
		# answered as plain HTTP. A piped connection is closed by the worker after its answer
		# (a WebSocket's handshake refused, a chunked body read), so nothing more the client
		# sends on it reaches the worker without the router reading it first
		connection = None
		upgrade = False
		if "upgrade" in headers:
			upgrade = headers["upgrade"].lower() == "websocket" and "upgrade" in tokens(headers.get("connection", ""))
			connection = b"Upgrade, close" if upgrade else b""
		if chunked and not upgrade:
			connection = b"close"

		path, _, query = target.partition("?")
		hint = None
		body = b""
		if path.startswith("/_domino/"):
			hint = worker_hint(path, query)
			# Uploads name their page in a header (core.js sends it with each one)
			if hint is None:
				hint = worker_of(headers.get("x-domino-page"))
			# Events POSTed by core.js carry their page id in the body
			if hint is None and method == "POST" and 0 < length <= MAX_PEEK and not chunked and "expect" not in headers:
				body = await self.reader.readexactly(length)
				length = 0
				hint = body_hint(body)

		worker = self.router.pick(hint, self.last)
		if hint is None:
			self.last = worker

		upstream = await self.upstream(worker)
		self.active = upstream
		upstream.waiting += 1
		self.router.waiting[worker] += 1
		upstream.writer.write(forward_head(lines, self.client, self.router.trusted, connection) + body)

		while length > 0:
			data = await self.reader.read(min(length, CHUNK))
			if not data:
				return False
			length -= len(data)
			upstream.writer.write(data)
			await upstream.writer.drain()
		await upstream.writer.drain()

		if upgrade or chunked:
			# A WebSocket (or a body of unknown length): the rest of the connection is theirs
			await pipe(self.reader, upstream.writer)
			return False

		return True


	async def upstream(self, worker):

		upstream = self.upstreams.get(worker)
		if upstream is not None and upstream.alive():
			return upstream

		# The workers' sockets listen for as long as the router runs, so while one restarts
		# this waits in its backlog instead of failing
		reader, writer = await asyncio.open_connection("127.0.0.1", self.router.ports[worker], limit=CHUNK)
		upstream = self.upstreams[worker] = Upstream(worker, reader, writer)
		upstream.pump = asyncio.ensure_future(self.pump(upstream))

		return upstream


	async def pump(self, upstream):
		"""Copy a worker's responses to the client."""

		try:
			while True:
				data = await upstream.reader.read(CHUNK)
				# A response has started (or the connection ended): the worker is on to it
				self.answered(upstream)
				if not data:
					break
				self.writer.write(data)
				await self.writer.drain()
		except OSError:
			pass
		finally:
			self.answered(upstream)
		close(upstream.writer)

		# The worker closed the connection the client is waiting on (after a response that
		# ends that way, or a keep-alive timeout): close the client's too, as it would have
		if upstream is self.active:
			close(self.writer)


	def answered(self, upstream):

		self.router.waiting[upstream.worker] -= upstream.waiting
		upstream.waiting = 0


	async def refuse(self, status, reason):

		if self.active is not None:
			return

		body = reason.encode()
		self.writer.write(b"HTTP/1.1 %d %s\r\nContent-Type: text/plain\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s" % (status, reason.encode(), len(body), body))
		try:
			await self.writer.drain()
		except OSError:
			pass


	async def finish(self):

		# The client is done sending. Tell the worker answering it, as a direct connection
		# would, and let the answer finish; the other connections just close
		active = self.active
		for upstream in self.upstreams.values():
			if upstream is not active:
				close(upstream.writer)

		if active is not None and active.alive():
			try:
				if active.writer.can_write_eof():
					active.writer.write_eof()
				await asyncio.wait_for(asyncio.shield(active.pump), GRACEFUL * 2)
			except (OSError, asyncio.TimeoutError):
				pass
			except asyncio.CancelledError:
				close(active.writer)
				raise

		for upstream in self.upstreams.values():
			close(upstream.writer)
			if upstream.pump is not None:
				upstream.pump.cancel()
		close(self.writer)


async def pipe(reader, writer):

	try:
		while True:
			data = await reader.read(CHUNK)
			if not data:
				return
			writer.write(data)
			await writer.drain()
	except OSError:
		pass


def close(writer):

	try:
		writer.close()
	except (OSError, RuntimeError):
		pass


# The workers


class Worker:
	"""One worker process, restarted when it exits. Its socket belongs to this process, so its
	port stays the same and connections wait in its backlog across restarts."""


	def __init__(self, context, location, id):

		self.context = context
		self.location = location
		self.id = id
		self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.socket.bind(("127.0.0.1", 0))
		self.socket.listen(2048)
		self.port = self.socket.getsockname()[1]
		self.process = None
		self.ready = None
		self.started = 0
		self.delay = 0
		self.restart_at = None


	def start(self):

		self.ready = self.context.Event()
		self.process = self.context.Process(target=worker_main, args=(self.location, self.id, self.socket, self.ready), name=f"domino-worker-{self.id}")
		self.process.start()
		self.started = time.monotonic()
		self.restart_at = None


	def alive(self):

		return self.process is not None and self.process.is_alive()


class Supervisor:


	def __init__(self, location, host, port, count):

		self.location = location
		self.host = host
		self.port = port
		# A fresh interpreter per worker: forking would copy this process's threads and loop
		self.context = multiprocessing.get_context("spawn")
		self.workers = [Worker(self.context, location, id) for id in range(1, count + 1)]
		self.stopping = False


	async def run(self):

		loop = asyncio.get_running_loop()
		self.stop = asyncio.Event()
		for signum in (signal.SIGINT, signal.SIGTERM):
			try:
				loop.add_signal_handler(signum, self.stop.set)
			except (NotImplementedError, RuntimeError):
				pass

		for worker in self.workers:
			worker.start()

		if not await self.wait_ready():
			return 0 if self.stop.is_set() else 1

		router = Router({worker.id: worker.port for worker in self.workers})
		server = await asyncio.start_server(router.handle, self.host, self.port, limit=MAX_HEAD, backlog=2048)
		port = server.sockets[0].getsockname()[1]
		count = len(self.workers)
		log(f"App: http://{self.host}:{port}/ ({count} worker{'s' if count > 1 else ''})")

		watcher = asyncio.ensure_future(self.watch())
		try:
			await self.stop.wait()
		finally:
			self.stopping = True
			watcher.cancel()
			server.close()
			# Workers end their connections as they stop; the router's go with them
			await loop.run_in_executor(None, self.stop_workers)
			for task in list(router.connections):
				task.cancel()

		return 0


	async def wait_ready(self):

		while not self.stop.is_set():
			if all(worker.ready.is_set() for worker in self.workers):
				return True
			for worker in self.workers:
				if not worker.alive() and not worker.ready.is_set():
					log(f"worker {worker.id} exited while starting (exit code {worker.process.exitcode})")
					return False
			await asyncio.sleep(0.05)

		return False


	async def watch(self):

		while not self.stopping:
			now = time.monotonic()
			for worker in self.workers:
				if worker.alive() or self.stopping:
					continue
				if worker.restart_at is None:
					# Pages on it are gone; their tabs reload when the new one doesn't know them
					ran = now - worker.started
					worker.delay = 0 if ran > STEADY else min(max(worker.delay * 2, 0.5), MAX_DELAY)
					worker.restart_at = now + worker.delay
					log(f"worker {worker.id} exited (exit code {worker.process.exitcode}); restarting")
				if now >= worker.restart_at:
					worker.start()
			await asyncio.sleep(0.2)


	def stop_workers(self):

		self.stopping = True

		for worker in self.workers:
			if worker.alive():
				worker.process.terminate()

		deadline = time.monotonic() + GRACEFUL + 2
		for worker in self.workers:
			if worker.process is None:
				continue
			worker.process.join(max(0, deadline - time.monotonic()))
			if worker.process.is_alive():
				worker.process.kill()
				worker.process.join()

		for worker in self.workers:
			worker.socket.close()


def worker_main(location, worker_id, sock, ready):
	"""A worker process: the app, served by uvicorn on the socket the router connects to."""

	import logging

	import uvicorn

	os.environ[WORKER_ID_ENV] = str(worker_id)

	# Ctrl+C reaches the router alone, which then stops the workers in order
	if hasattr(os, "setpgrp"):
		os.setpgrp()
	watch_parent()

	asgi = load_asgi(location)

	config = uvicorn.Config(asgi, timeout_graceful_shutdown=GRACEFUL,
		ws_per_message_deflate=bool(asgi.app.config["DOMINO_WS_COMPRESSION"]))
	# The address users need is the router's, which it prints
	logging.getLogger("uvicorn.error").addFilter(lambda record: not str(record.msg).startswith("Uvicorn running on"))

	ready.set()
	uvicorn.Server(config).run(sockets=[sock])


def load_asgi(location):

	from .asgi import ENV_APP, from_environ
	from .cli import load_app

	if os.path.exists(location):
		return load_app(location).asgi

	# "path/to/app.py:attribute", from app.run(workers=N)
	os.environ[ENV_APP] = location

	return from_environ()


def watch_parent():
	"""Stop this worker if the router's process dies, even from SIGKILL, so none is orphaned."""

	parent = multiprocessing.parent_process()
	if parent is None:
		return

	def wait():
		multiprocessing.connection.wait([parent.sentinel])
		# uvicorn stops gracefully on SIGTERM
		os.kill(os.getpid(), signal.SIGTERM)

	threading.Thread(target=wait, name="domino-parent", daemon=True).start()
