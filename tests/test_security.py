"""Regression tests for the security audit of October 2026 (docs/research/security-audit-2026-10.md).
Each test is named after what it protects against."""

import asyncio
import re
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

	async def stop():
		server.close()
		for task in list(routing.connections):
			task.cancel()
		try:
			await asyncio.wait_for(server.wait_closed(), 2)
		except asyncio.TimeoutError:
			pass

	asyncio.run_coroutine_threadsafe(stop(), loop).result(5)
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


# Events --------------------------------------------------------------------------------------


def test_form_fields_cant_carry_mongodb_operators():

	import domino.tags as t
	from domino import Collection
	from domino.components import Document

	users = Collection()
	users.insert({"email": "ada@example.com", "secret": "ada's"})
	found = []

	class Lookup(t.form):

		def init(self):
			self.configure(on_submit=self.look)

		def render(self):
			return [t.input(name="email"), t.input(name="tags")]

		def look(self, event):
			found.append((dict(event.form), users.find_one({"email": event.form.get("email")})))

	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document() [Lookup()]

	client = app.test_client()
	page_id, event_id = page_and_event(client.get("/").get_data(as_text=True))

	# Not what core.js sends, but anyone can send it: {"$ne": null} matches every document
	form = {"email": {"$ne": None}, "tags": ["a", {"$gt": ""}], "count": 5}
	response = client.post("/_domino/events", json={"page_id": page_id, "event_id": event_id, "data": {"form": form}})
	assert response.status_code == 200

	assert found == [({"tags": ["a"]}, None)]


def test_a_page_id_alone_doesnt_act_as_its_user(monkeypatch):

	import domino.tags as t
	from domino import Collection, accounts
	from domino.components import Document

	monkeypatch.setattr(accounts, "users", Collection())
	accounts._failures.clear()
	accounts.create_user("ada@example.com", "correct horse")
	seen = []

	class Private(t.div):

		def render(self):
			return [t.button(on_click=self.whoami) ["?"]]

		def whoami(self):
			seen.append(accounts.current_user()["email"])

	app = Domino(__name__)
	app.secret_key = "test"

	@app.route("/")
	def index():
		return Document() [Private(), accounts.LoginForm()]

	ada = app.test_client()
	html = ada.get("/").get_data(as_text=True)
	login_page, _ = page_and_event(html)
	submit = re.search(r'data-event-id="([^"]+-submit)"', html).group(1)
	form = {"email": "ada@example.com", "password": "correct horse"}
	assert ada.post("/_domino/events", json={"page_id": login_page, "event_id": submit, "data": {"form": form}}).status_code == 200

	# A page made for Ada, signed in
	html = ada.get("/").get_data(as_text=True)
	page_id, whoami = page_and_event(html)
	assert "Signed in as" in html

	# Someone who learned its id (from a log of the /_domino/ws?page= URLs, say) can't use it
	stranger = app.test_client()
	assert stranger.post("/_domino/events", json={"page_id": page_id, "event_id": whoami}).status_code == 404
	assert seen == []

	assert ada.post("/_domino/events", json={"page_id": page_id, "event_id": whoami}).status_code == 200
	assert seen == ["ada@example.com"]


# Accounts ------------------------------------------------------------------------------------


@pytest.fixture
def users(monkeypatch):

	from domino import Collection, accounts

	collection = Collection()
	monkeypatch.setattr(accounts, "users", collection)
	accounts._failures.clear()
	accounts._mailed.clear()

	return collection


def test_reset_links_dont_follow_a_forged_host_header(users, monkeypatch):

	from domino import accounts, mail

	app = Domino(__name__)
	app.secret_key = "test"
	user = accounts.create_user("victim@example.com", "correct horse")

	# Emails that really go out (SMTP) with no public_url: the link would be built on the Host
	# header of the attacker's request for the victim's reset, http://evil.example/reset-password?token=...
	monkeypatch.setattr(mail, "testing", False)
	app.settings["mail"] = {"backend": "smtp", "host": "127.0.0.1", "from": "app@example.com"}
	with app.test_request_context("/forgot-password", base_url="http://evil.example"):
		with pytest.raises(accounts.AccountsConfigError, match="public_url"):
			accounts.send_reset_email(user)

	# With public_url, the Host header doesn't matter
	app.settings["mail"] = {"backend": "memory"}
	app.settings["public_url"] = "https://example.com"
	mail.outbox.clear()
	with app.test_request_context("/forgot-password", base_url="http://evil.example"):
		accounts.send_reset_email(user)
	assert mail.outbox[0].links[0].startswith("https://example.com/reset-password?token=")
	mail.outbox.clear()


@pytest.mark.parametrize("email", ["victim,attacker@evil.example", "a@b.example\r\nBcc: c@d.example", "<a@b.example>", "\"a\"@b.example", "a;b@c.example"])
def test_account_emails_are_one_plain_address(users, email):

	from domino import accounts

	# "victim,attacker@evil.example" is two addresses in a To: header
	with pytest.raises(accounts.AccountError):
		accounts.create_user(email, "correct horse")


def test_signup_email_check_takes_linear_time(users):

	import time

	from domino import accounts

	# The old pattern backtracked over "a.a.a...": 16 KB took 1.5 s, an event's 1 MB hours
	email = "a@" + "a." * 100000 + " "

	start = time.perf_counter()
	assert accounts.EMAIL_PATTERN.match(email) is None
	with pytest.raises(accounts.AccountError):
		accounts.create_user(email, "correct horse")
	assert time.perf_counter() - start < 1

	assert accounts.EMAIL_PATTERN.match("ada.lovelace+x@mail.example.co.uk")


def test_reset_links_stop_working_when_the_email_changes(users):

	from domino import accounts, mail

	app = Domino(__name__)
	app.secret_key = "test"
	app.settings["public_url"] = "https://example.com"
	accounts.create_user("old@example.com", "correct horse")
	user = users.find_one({"email": "old@example.com"})  # with its password hash, as the form finds it

	mail.outbox.clear()
	with app.app_context():
		accounts.send_reset_email(user)
		token = mail.outbox[0].links[0].split("token=")[1]
		mail.outbox.clear()
		assert accounts._reset_user(token) is not None

		# The account moved to a new address; a link sent to the old one (a mailbox someone else
		# may now read) no longer resets its password
		users.update({"_id": user["_id"]}, {"$set": {"email": "new@example.com"}})
		with pytest.raises(accounts.AccountError, match="invalid"):
			accounts.reset_password(token, "a new password")


def test_oauth_callback_url_uses_public_url(users):

	from urllib.parse import parse_qs, urlsplit

	app = Domino(__name__)
	app.secret_key = "test"
	app.settings["accounts"] = {"github": {"client_id": "id", "client_secret": "shh"}}
	app.settings["public_url"] = "https://example.com"

	response = app.test_client().get("/_domino/accounts/github/login", headers={"Host": "evil.example"})
	query = parse_qs(urlsplit(response.headers["Location"]).query)

	assert query["redirect_uri"] == ["https://example.com/_domino/accounts/github/callback"]


# Deployment ----------------------------------------------------------------------------------


def test_platform_configs_trust_only_the_platform_proxy(tmp_path, monkeypatch, capsys):

	from domino import deploy

	(tmp_path / "app.py").write_text("from domino import Domino\napp = Domino(__name__)\n", encoding="utf-8")
	for name in ("DOMINO_MONGO__URL", "MONGO_URL", "DOMINO_SECRET_KEY"):
		monkeypatch.delenv(name, raising=False)
	monkeypatch.setattr(deploy.shutil, "which", lambda name: None)

	# Without it every visitor has the proxy's address: 20 wrong passwords from anyone lock
	# everyone out of logging in (the per-address limit), and 12 reset emails stop all emails
	deploy.deploy_fly(tmp_path, name="shop")
	fly = (tmp_path / "fly.toml").read_text()
	assert f'FORWARDED_ALLOW_IPS = "{deploy.PLATFORM_PROXIES}"' in fly
	assert 'DOMINO_PUBLIC_URL = "https://shop.fly.dev"' in fly

	deploy.deploy_render(tmp_path, name="shop")
	assert f'value: "{deploy.PLATFORM_PROXIES}"' in (tmp_path / "render.yaml").read_text()
	assert "DOMINO_PUBLIC_URL" in capsys.readouterr().out

	assert "*" not in deploy.PLATFORM_PROXIES
	trusted = {entry for entry in deploy.PLATFORM_PROXIES.split(",")}
	assert workers.is_trusted("10.0.3.4", trusted) and workers.is_trusted("fdaa:0:1::2", trusted)
	assert not workers.is_trusted("203.0.113.9", trusted)

	# A visitor's own X-Forwarded-For entry doesn't count: the proxy appends the real address
	lines = [b"GET / HTTP/1.1", b"X-Forwarded-For: 10.9.9.9, 203.0.113.9"]
	assert workers.forward_head(lines, "10.0.3.4", trusted).endswith(b"X-Forwarded-For: 10.9.9.9, 203.0.113.9, 10.0.3.4\r\n\r\n")


def test_serve_warns_about_debug_mode(capsys):

	app = Domino(__name__)
	app.debug = True
	workers.warn_if_debug(app)
	assert "debug mode" in capsys.readouterr().err

	app.debug = False
	workers.warn_if_debug(app)
	assert capsys.readouterr().err == ""


# Limits (denial of service) ----------------------------------------------------------------


def slow_app():

	import time as time_

	import domino.tags as t
	from domino.components import Document

	app = Domino(__name__)
	app.config["DOMINO_MAX_EVENT_MB"] = 0.01  # 10 KB

	class Slow(t.div):

		def render(self):
			return [t.button(on_click=self.wait) ["wait"]]

		def wait(self):
			time_.sleep(0.05)

	@app.route("/")
	def index():
		return Document() [Slow()]

	return app


def page_and_event(html):

	return re.search(r'data-domino-page="([^"]+)"', html).group(1), re.search(r'data-event-id="([^"]+)"', html).group(1)


def test_huge_event_bodies_are_refused_unread():

	app = slow_app()
	client = app.test_client()
	page_id, event_id = page_and_event(client.get("/").get_data(as_text=True))

	big = {"page_id": page_id, "event_id": event_id, "data": {"value": "x" * 20000}}
	assert client.post("/_domino/events", json=big).status_code == 413
	assert client.post("/_domino/events", json={"page_id": page_id, "event_id": event_id}).status_code == 200

	# Ids of the wrong type, or JSON nested too deep, aren't errors on the server
	assert client.post("/_domino/events", json={"page_id": ["x"], "event_id": {"a": 1}}).status_code == 404
	assert client.post("/_domino/events", data="[" * 5000 + "]" * 5000, content_type="application/json").status_code == 404


def test_websocket_messages_are_limited_in_size_and_number(asgi_server):

	import json
	import urllib.request

	from websockets.exceptions import ConnectionClosed
	from websockets.sync.client import connect

	server = asgi_server(slow_app())
	page_id, event_id = page_and_event(urllib.request.urlopen(server.url).read().decode())

	with connect(f"{server.ws_url}?page={page_id}", open_timeout=5) as ws:
		ws.send(json.dumps({"type": "hello", "page_id": page_id}))
		assert json.loads(ws.recv(5)) == {"type": "ready"}
		ws.send(json.dumps({"type": "event", "ref": 1, "page_id": page_id, "event_id": event_id, "data": {"value": "x" * 20000}}))
		with pytest.raises(ConnectionClosed) as closed:
			while True:
				ws.recv(5)
		assert closed.value.rcvd.code == 1009

	# Events sent far faster than they're handled (each takes 50 ms) aren't queued without end
	with connect(f"{server.ws_url}?page={page_id}", open_timeout=5) as ws:
		ws.send(json.dumps({"type": "hello", "page_id": page_id}))
		assert json.loads(ws.recv(5)) == {"type": "ready"}
		with pytest.raises(ConnectionClosed) as closed:
			for ref in range(1000):
				ws.send(json.dumps({"type": "event", "ref": ref, "page_id": page_id, "event_id": event_id, "data": {}}))
			while True:
				ws.recv(5)
		assert closed.value.rcvd.code == 1008


def test_unclaimed_uploads_cant_pile_up():

	import io

	from werkzeug.datastructures import FileStorage, MultiDict

	from domino.uploads import Uploads

	uploads = Uploads({"DOMINO_MAX_UPLOAD_MB": 1, "DOMINO_MAX_PENDING_UPLOADS_MB": 3, "DOMINO_UPLOAD_TTL": 600})
	megabyte = b"x" * (1024 * 1024)

	def upload(page_id):
		return uploads.add(page_id, MultiDict([("file", FileStorage(io.BytesIO(megabyte), "a.bin"))]))["file"][0]

	# One page uploading again and again without sending its events keeps two uploads' worth
	tokens = [upload("page-1") for _ in range(10)]
	assert len(uploads) == 2
	assert set(uploads.files) == set(tokens[-2:])

	# And all pages together DOMINO_MAX_PENDING_UPLOADS_MB
	for number in range(10):
		upload(f"other-{number}")
	assert sum(entry[2].size for entry in uploads.files.values()) <= 3 * 1024 * 1024
	assert len(uploads) == 3


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
