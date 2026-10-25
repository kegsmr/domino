"""Regression tests for the security audit of October 2026 (docs/research/security-audit-2026-10.md).
Each test is named after what it protects against."""

import asyncio
import socket
import threading
import types

import pytest

import domino.workers as workers

from conftest import ASGIServer


# The router of `domino serve --workers N` (domino.workers) -------------------------------------


async def client_address(scope, receive, send):
	"""A worker that answers with the address uvicorn says the request came from."""

	if scope["type"] != "http":
		return

	while (await receive()).get("more_body"):
		pass

	body = (scope["client"][0] if scope.get("client") else "-").encode()
	await send({"type": "http.response.start", "status": 200, "headers": [(b"content-length", str(len(body)).encode())]})
	await send({"type": "http.response.body", "body": body})


@pytest.fixture
def router():
	"""A router in front of one uvicorn worker (which trusts X-Forwarded-For from 127.0.0.1, the
	router) for clients it doesn't trust as proxies. Returns a function that sends raw bytes on
	one connection and returns everything that comes back."""

	worker = ASGIServer(types.SimpleNamespace(asgi=client_address))
	loop = asyncio.new_event_loop()
	thread = threading.Thread(target=loop.run_forever, daemon=True)
	thread.start()

	routing = workers.Router({1: worker.port})
	routing.trusted = set()  # the test client (127.0.0.1) is an ordinary visitor here

	async def start():
		return await asyncio.start_server(routing.handle, "127.0.0.1", 0, limit=workers.MAX_HEAD)

	server = asyncio.run_coroutine_threadsafe(start(), loop).result(5)
	port = server.sockets[0].getsockname()[1]

	def send(payload, timeout=1.5):
		with socket.create_connection(("127.0.0.1", port), 5) as connection:
			connection.settimeout(timeout)
			connection.sendall(payload)
			received = b""
			try:
				while True:
					chunk = connection.recv(65536)
					if not chunk:
						break
					received += chunk
			except socket.timeout:
				pass
		return received

	yield send

	server.close()
	asyncio.run_coroutine_threadsafe(server.wait_closed(), loop).result(5)
	loop.call_soon_threadsafe(loop.stop)
	thread.join(5)
	worker.stop()


SPOOFED = b"GET / HTTP/1.1\r\nHost: example.com\r\nX-Forwarded-For: 203.0.113.66\r\n\r\n"


def test_router_drops_x_forwarded_for_from_visitors(router):

	answer = router(SPOOFED)

	assert answer.endswith(b"127.0.0.1")
	assert b"203.0.113.66" not in answer


def test_no_request_smuggled_after_a_chunked_body(router):

	# The router pipes a connection once a body has no length; a request after the body went
	# straight to the worker, which believed its X-Forwarded-For (a lockout bypass)
	answer = router(b"POST / HTTP/1.1\r\nHost: example.com\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n" + SPOOFED)

	assert b"203.0.113.66" not in answer
	assert answer.startswith(b"HTTP/1.1 200")


def test_no_request_smuggled_after_an_upgrade_that_isnt_a_websocket(router):

	answer = router(b"GET / HTTP/1.1\r\nHost: example.com\r\nConnection: Upgrade\r\nUpgrade: h2c\r\n\r\n" + SPOOFED)

	assert b"203.0.113.66" not in answer
	# Answered as plain HTTP, both requests
	assert answer.count(b"HTTP/1.1 200") == 2


def test_no_request_smuggled_after_a_refused_websocket_handshake(router):

	answer = router(b"GET / HTTP/1.1\r\nHost: example.com\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n" + SPOOFED)

	assert b"203.0.113.66" not in answer


@pytest.mark.parametrize("head", [
	# A header only a lenient worker sees, hidden behind a bare \n
	b"POST / HTTP/1.1\r\nHost: x\r\nX-A: 1\nTransfer-Encoding: chunked\r\nContent-Length: 5\r\n\r\n0\r\n\r\n",
	# Folded header lines (obsolete)
	b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 5\r\n Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
	# Both a length and chunks
	b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 5\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
	# Lengths that parsers read differently
	b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: +5\r\n\r\nhello",
	b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 0x5\r\n\r\nhello",
	b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length : 5\r\n\r\nhello",
])
def test_ambiguous_requests_are_refused(router, head):

	assert router(head).startswith(b"HTTP/1.1 400")


def test_trusted_proxies_can_be_networks(monkeypatch):

	monkeypatch.setenv("FORWARDED_ALLOW_IPS", "127.0.0.1, 10.0.0.0/8, fc00::/7")
	trusted = workers.trusted_hosts()

	assert workers.is_trusted("10.1.2.3", trusted)
	assert workers.is_trusted("fdaa::3", trusted)
	assert workers.is_trusted("127.0.0.1", trusted)
	assert not workers.is_trusted("203.0.113.9", trusted)
	assert not workers.is_trusted(None, trusted)

	lines = [b"GET / HTTP/1.1", b"X-Forwarded-For: 203.0.113.9"]
	assert b"203.0.113.9, 10.1.2.3" in workers.forward_head(lines, "10.1.2.3", trusted)
	assert b"203.0.113.9" not in workers.forward_head(lines, "198.51.100.7", trusted)
