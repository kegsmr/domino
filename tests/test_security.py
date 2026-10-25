"""Regression tests for the security audit of October 2026 (docs/research/security-audit-2026-10.md).
Each test is named after what it protects against."""

import asyncio
import socket
import threading
import types

import pytest
from flask import session

import domino.workers as workers
from domino import Domino
from domino.core import Page

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


# Rendering ---------------------------------------------------------------------------------


@pytest.mark.parametrize("name", [
	'onmouseover=alert(1) x',
	'x" onclick="alert(1)',
	"x><script>alert(1)</script",
	"a/b",
	"a\tb",
	"",
])
def test_attribute_names_from_data_cant_inject_html(name):

	import domino.tags as t

	# Attributes from data, e.g. t.div(**attrs) or <div {attrs}> in a template string
	with pytest.raises(ValueError, match="Invalid attribute name"):
		t.div(**{name: "1"})._render()


def test_valid_attribute_names_render():

	import domino.tags as t

	html = t.div(**{"data_x": 1, "aria-label": "x", "xml:lang": "en", "@click": "go()", "x.y": "1"})._render()

	assert 'data-x="1"' in html and 'aria-label="x"' in html and 'xml:lang="en"' in html and '@click="go()"' in html


def test_script_and_style_text_cant_end_their_element():

	import domino.tags as t

	payload = "</SCRIPT><img src=x onerror=alert(1)>"
	html = t.script() [f"const name = {payload!r};"]._render()
	assert "</SCRIPT><img" not in html
	assert "<\\/SCRIPT><img" in html and html.rstrip().endswith("</script>")

	html = t.script(inner="x = '</script >'")._render()
	assert html.count("</script") == 1

	html = t.style() ["p::after { content: '</style><img src=x onerror=alert(1)>' }"]._render()
	assert "</style><img" not in html
	assert html.count("</style") == 1


def test_client_components_render_names_and_scripts_the_same_way():

	from domino import client

	tags = client.shim().tags

	with pytest.raises(ValueError, match="Invalid attribute name"):
		tags.div(**{'x" onclick="alert(1)': "1"})._render()

	html = tags.script() ["a = '</Script><img src=x onerror=alert(1)>'"]._render()
	assert html == "<script>a = '<\\/Script><img src=x onerror=alert(1)>'</script>"


# The session hand-off (/_domino/session/<token>) ---------------------------------------------


def handoff_token(app, page=None):
	"""A token for a session changed by an event, as a WebSocket event would get one."""

	with app.test_request_context():
		session["user"] = "attacker"
		token, cookies = app.session_handoff(session, page)

	assert token and cookies
	return token


def test_another_site_cant_plant_a_session_with_a_hand_off_token():

	app = Domino(__name__)
	app.secret_key = "test"
	page = Page()
	client = app.test_client()

	# What a cross-site <form method=post action=".../_domino/session/<token>"> sends: no custom
	# header. The token (of the attacker's own login, say) isn't used up
	token = handoff_token(app, page)
	response = client.post(f"/_domino/session/{token}", content_type="application/x-www-form-urlencoded")
	assert response.status_code == 403
	assert "Set-Cookie" not in response.headers

	# Nor by another page
	response = client.post(f"/_domino/session/{token}", headers={"X-Domino-Page": "another-page"})
	assert response.status_code == 403
	assert "Set-Cookie" not in response.headers

	# The page whose event changed the session gets the cookie, once
	response = client.post(f"/_domino/session/{token}", headers={"X-Domino-Page": page.id})
	assert response.status_code == 204
	assert response.headers["Set-Cookie"].startswith("session=")
	assert client.post(f"/_domino/session/{token}", headers={"X-Domino-Page": page.id}).status_code == 404


def test_core_js_claims_the_hand_off_with_its_page(asgi_server, monkeypatch):

	sync_api = pytest.importorskip("playwright.sync_api")

	import domino.tags as t
	from domino import Collection, accounts
	from domino.components import Document

	monkeypatch.setattr(accounts, "users", Collection())
	accounts._failures.clear()
	accounts.create_user("ada@example.com", "correct horse")

	app = Domino(__name__)
	app.secret_key = "test"
	app.config["DOMINO_SECURE_COOKIES"] = False  # plain http://127.0.0.1

	@app.route("/")
	def index():
		return Document() [t.main() [accounts.UserMenu(), accounts.LoginForm()]]

	server = asgi_server(app)

	with sync_api.sync_playwright() as playwright:
		browser = playwright.chromium.launch()
		try:
			page = browser.new_page()
			claims = []
			page.on("response", lambda response: "/_domino/session/" in response.url and claims.append(response.status))
			page.goto(server.url)
			page.fill("input[name=email]", "ada@example.com")
			page.fill("input[name=password]", "correct horse")
			page.get_by_role("button", name="Log in").click()
			page.locator(".UserMenu").get_by_text("Signed in as").wait_for()
			page.wait_for_timeout(200)

			# Logged in over the WebSocket, so the cookie came through the hand-off
			assert claims == [204]
			page.reload()
			assert "Signed in as" in page.locator(".UserMenu").inner_text()
		finally:
			browser.close()
