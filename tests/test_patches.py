"""Patches (a component sent as what changed), and hidden tabs that pause their page."""

import json
import random
import threading
import time

import pytest

import domino.tags as t
from domino import Collection, Domino, State, patches, reactive
from domino.components import Document
from domino.patches import Patcher, apply, diff


def rendered_list(count, prefix="item"):
	"""HTML as the renderer makes it: one element per line, indented."""

	return t.div(id="list") [
		t.ul()([
			t.li(class_="row") [
				t.span() [f"{prefix} {number}"],
				t.button() ["remove"]
			]
			for number in range(count)
		]),
		t.p() [f"{count} items"]
	]._render()


def roundtrip(old, new):

	ops = diff(old, new)
	if ops is not None:
		assert apply(old, ops) == new
		# What goes over the wire is JSON; it must survive the trip
		assert apply(old, json.loads(json.dumps(ops))) == new

	return ops


def test_random_edits_to_rendered_html_roundtrip():

	rng = random.Random(1234)
	html = rendered_list(60)

	for _ in range(500):
		lines = html.split("\n")
		for _ in range(rng.randint(0, 8)):
			edit = rng.random()
			at = rng.randrange(len(lines))
			if edit < 0.25:
				del lines[at]
			elif edit < 0.5:
				lines.insert(at, rng.choice(lines))  # a repeated line, like </li>
			elif edit < 0.7:
				lines.insert(at, f"        <b>{rng.random()} ünï 😀</b>")
			elif edit < 0.85:
				lines[at] = lines[at].replace("item", "thing")
			else:
				# A block moved elsewhere
				end = min(len(lines), at + rng.randint(1, 10))
				block = lines[at:end]
				del lines[at:end]
				lines[rng.randrange(len(lines) + 1):0] = block
		new = "\n".join(lines)
		roundtrip(html, new)
		# Sometimes keep going from the edited HTML, as successive updates do
		if rng.random() < 0.3:
			html = new


def test_one_changed_line_is_a_small_patch():

	old = rendered_list(100)
	new = old.replace("item 50\n", "changed 50\n")

	ops = roundtrip(old, new)

	assert len(ops) == 3
	assert ops[1] == "                changed 50"
	assert len(json.dumps(ops)) < 60


def test_an_appended_item_and_a_shifted_list():

	old = rendered_list(100)

	appended = roundtrip(old, rendered_list(101))
	assert sum(len(op) for op in appended if isinstance(op, str)) < 200

	# A removed first item shifts every line, but they're copied
	lines = old.split("\n")
	removed = "\n".join(lines[:2] + lines[9:])
	assert sum(len(op) for op in roundtrip(old, removed) if isinstance(op, str)) < 100


def test_edge_cases():

	html = rendered_list(30)

	for old, new in [
		("", ""),
		("", html),
		(html, ""),
		(html, html),
		("\n", "\n\n"),
		("a", "b"),
		(html, html + "\n"),
		(html, "\n" + html),
		(html, html.replace("\n", "\r\n")),
		("é\n😀\nx", "é\n😀\ny"),
	]:
		roundtrip(old, new)

	# Nothing in common: sending the new HTML whole is smaller
	assert diff(html, "\n".join(f"<b>{number * 7919}</b>" for number in range(300))) is None
	assert diff(html, "x" * len(html)) is None
	# Unchanged: copy it all
	assert diff(html, html) == [[0, len(html.split("\n"))]]


def test_unicode_lines_are_counted_as_lines_not_bytes():

	old = "\n".join(f"<li>ünïcödé {number} 😀 {'ж' * 40}</li>" for number in range(50))
	new = old.replace("ünïcödé 25 ", "ascii 25 ")

	ops = roundtrip(old, new)

	assert ops[1] == f"<li>ascii 25 😀 {'ж' * 40}</li>"


def test_huge_html_diffs_quickly():

	old = rendered_list(20000)  # about 2 MB
	new = old.replace("item 10000\n", "item ten thousand\n").replace("20000 items", "19999 items")

	started = time.perf_counter()
	ops = roundtrip(old, new)
	took = time.perf_counter() - started

	assert len(json.dumps(ops)) < 200
	assert took < 1


def test_patcher_sends_html_then_patches_against_what_it_sent():

	patcher = Patcher()
	old, new = rendered_list(100), rendered_list(101)

	first = patcher.encode({"type": "update", "id": "list", "html": old, "version": 3})
	second = patcher.encode({"type": "update", "id": "list", "html": new, "version": 7, "css": [["A", "a"]]})

	assert first["html"] == old
	assert "html" not in second
	assert second["base"] == 3
	assert second["version"] == 7
	assert second["css"] == [["A", "a"]]
	assert apply(old, second["patch"]) == new


def test_patcher_leaves_small_html_and_bigger_patches_alone():

	patcher = Patcher()

	small = {"id": "a", "html": "<p>1</p>", "version": 1}
	assert patcher.encode(small) is small
	assert patcher.encode({"id": "a", "html": "<p>2</p>", "version": 2})["html"] == "<p>2</p>"
	assert "a" not in patcher.sent

	# Not smaller: the whole HTML, which becomes the next base
	patcher.encode({"id": "b", "html": rendered_list(50), "version": 1})
	other = "\n".join(f"<b>{number * 7919}</b>" for number in range(300))
	assert patcher.encode({"id": "b", "html": other, "version": 2})["html"] == other
	assert patcher.sent["b"] == (2, other)

	# Messages without HTML (an event that re-rendered nothing, errors) pass through
	for message in ({"id": None, "html": None}, {"error": "nope"}, {"type": "ready"}):
		assert patcher.encode(message) is message


def test_patcher_memory_is_capped_least_recently_sent_first():

	html = rendered_list(40)
	patcher = Patcher(limit=len(html) * 3 + 10)

	for key in "abcd":
		patcher.encode({"id": key, "html": html + key, "version": 1})

	assert list(patcher.sent) == ["b", "c", "d"]
	assert patcher.size == sum(len(kept) for _, kept in patcher.sent.values()) <= patcher.limit

	# Sending one again makes it the most recent; an evicted one is sent whole
	patcher.encode({"id": "b", "html": html + "b!", "version": 2})
	assert list(patcher.sent) == ["c", "d", "b"]
	assert "html" in patcher.encode({"id": "a", "html": html + "a!", "version": 2})
	assert list(patcher.sent) == ["d", "b", "a"]

	# Bigger than the whole limit: sent, never kept
	huge = rendered_list(200)
	assert patcher.encode({"id": "e", "html": huge, "version": 1})["html"] == huge
	assert "e" not in patcher.sent

	patcher.clear()
	assert patcher.size == 0 and not patcher.sent


def test_patcher_resend_gives_the_last_html_whole():

	patcher = Patcher()
	html = rendered_list(30)
	patcher.encode({"id": "list", "html": html, "version": 4})

	assert patcher.resend("list") == {"type": "update", "id": "list", "html": html, "version": 4}
	assert patcher.resend("unknown") is None


def test_one_diff_for_the_same_html_on_many_sockets(monkeypatch):

	old, new = rendered_list(50), rendered_list(51)
	calls = []
	real = patches.diff
	monkeypatch.setattr(patches, "diff", lambda a, b: calls.append(1) or real(a, b))

	sockets = [Patcher() for _ in range(20)]
	for patcher in sockets:
		patcher.encode({"id": "list", "html": old, "version": 1})
	results = [patcher.encode({"id": "list", "html": new, "version": 2}) for patcher in sockets]

	assert len(calls) == 1
	assert all(result["patch"] == results[0]["patch"] for result in results)


# Predicted states (see domino.optimistic): large ones are patches against the first


class Picker(t.div):

	picked = State(0)


	def render(self):

		return [
			t.ul()([
				t.li(class_="picked" if number == self.picked else None) [
					t.button(on_click=lambda event, number=number: self.pick(number)) [
						f"Option number {number}, with a description long enough to matter"
					]
				]
				for number in range(30)
			])
		]


	def pick(self, number):

		self.picked = number


def predictions(html):

	return json.loads(html.split("data-domino-predict>")[1].split("</script>")[0].replace("<\\/", "</"))


def test_large_predicted_states_are_patches_against_the_first():

	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document() [Picker()]

	html = app.test_client().get("/").get_data(as_text=True)
	graph = predictions(html)

	base = graph["base"]
	assert isinstance(graph["states"][base], str)
	patched = [state for state in graph["states"] if isinstance(state, list)]
	assert len(patched) >= 5
	# Each differs from the first in a couple of lines
	assert all(len(json.dumps(state)) < 300 for state in patched)

	for index, state in enumerate(graph["states"]):
		if isinstance(state, list):
			text = apply(graph["states"][base], state)
			assert "Option number 29" in text and 'class="picked"' in text


def test_small_predicted_states_stay_html():

	class Toggle(t.div):

		open = State(False)

		def render(self):
			return [t.button(on_click=self.toggle) ["Toggle"], t.p() ["open" if self.open else "closed"]]

		def toggle(self):
			self.open = not self.open

	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document() [Toggle()]

	graph = predictions(app.test_client().get("/").get_data(as_text=True))

	assert "base" not in graph
	assert all(state is None or isinstance(state, (str, int)) for state in graph["states"])


# Over the WebSocket


websockets_client = pytest.importorskip("websockets.sync.client")


messages = Collection()


class Feed(t.div):
	"""A live list, long enough to be patched; counts its renders (in its app's list)."""

	renders = None


	def render(self):

		# Not the render predicting what Clear shows (see domino.optimistic)
		if not reactive.is_predicting():
			self.renders.append(self)

		return [
			t.ul()([
				t.li() [
					t.strong() [message["name"]],
					f" {message['text']}"
				]
				for message in messages.find(sort="sent")
			]),
			t.button(on_click=self.clear) ["Clear"]
		]


	def clear(self):

		messages.remove({})


def make_app(**config):

	app = Domino(__name__)
	app.config["DOMINO_KEEPALIVE"] = 0.1
	app.config.update(config)

	# Feeds of this app only: other tests' pages may still be around, subscribed too
	class AppFeed(Feed):
		renders = []

	app.renders = AppFeed.renders

	@app.route("/")
	def index():
		return Document() [AppFeed()]

	return app


@pytest.fixture(autouse=True)
def fresh_feed():

	from domino import reactive

	messages.remove({})
	for number in range(40):
		messages.insert({"name": "ada", "text": f"Message number {number}", "sent": number})
	reactive.wait()

	yield

	reactive.wait()


def say(number):

	from domino import reactive

	messages.insert({"name": "bob", "text": f"Message number {number}", "sent": number})
	reactive.wait()


def load(server):

	import urllib.request

	html = urllib.request.urlopen(server.url).read().decode()
	page_id = html.split('data-domino-page="')[1].split('"')[0]
	event_ids = [part.split('"')[0] for part in html.split('data-event-id="')[1:]]

	return page_id, event_ids


class Tab:
	"""A socket that keeps the last HTML per component, as core.js does."""


	def __init__(self, server, page_id, patch=True):

		self.ws = websockets_client.connect(server.ws_url, open_timeout=5).__enter__()
		self.page_id = page_id
		self.bases = {}
		self.ws.send(json.dumps({"type": "hello", "page_id": page_id, "patch": patch}))
		assert self.receive() == {"type": "ready"}


	def receive(self, timeout=5):

		data = json.loads(self.ws.recv(timeout))
		if "patch" in data:
			version, html = self.bases[data["id"]]
			assert version == data["base"]
			data["patched"] = True
			data["html"] = apply(html, data.pop("patch"))
		if data.get("html"):
			self.bases[data["id"]] = (data["version"], data["html"])

		return data


	def nothing(self, timeout=0.3):

		with pytest.raises(TimeoutError):
			self.ws.recv(timeout)


	def send(self, **message):

		self.ws.send(json.dumps(message))


	def close(self):

		self.ws.close()


def test_pushes_after_the_first_are_patches(asgi_server):

	server = asgi_server(make_app())
	page_id, _ = load(server)
	tab = Tab(server, page_id)

	say(100)
	first = tab.receive()
	say(101)
	second = tab.receive()
	tab.close()

	assert "patched" not in first and "Message number 100" in first["html"]
	assert second["patched"] and "Message number 101" in second["html"]
	assert second["html"].count("<li>") == 42


def test_event_results_are_patched_too(asgi_server):

	server = asgi_server(make_app())
	page_id, (clear,) = load(server)
	tab = Tab(server, page_id)

	say(100)
	before = tab.receive()
	tab.send(type="event", ref=1, page_id=page_id, event_id=clear, data={})
	result = tab.receive()
	tab.close()

	# Everything went, so the result is mostly new: here, whole
	assert result["type"] == "result" and result["status"] == 200
	assert "<li>" not in result["html"] and "<li>" in before["html"]


def test_no_patches_without_asking_or_with_the_setting_off(asgi_server):

	for number, (app, patch) in enumerate(((make_app(), False), (make_app(DOMINO_PATCHES=False), True))):
		server = asgi_server(app)
		page_id, _ = load(server)
		tab = Tab(server, page_id, patch=patch)
		updates = []
		for message in range(2):
			say(100 + number * 10 + message)
			updates.append(tab.receive())
		tab.close()

		assert not any("patched" in update for update in updates)


def test_a_browser_that_lost_its_base_asks_for_the_html_again(asgi_server):

	server = asgi_server(make_app())
	page_id, _ = load(server)
	tab = Tab(server, page_id)

	say(100)
	first = tab.receive()
	tab.bases.clear()  # as if a message had been lost

	say(101)
	raw = json.loads(tab.ws.recv(5))
	assert "patch" in raw and raw["base"] == first["version"]

	# core.js asks for the whole HTML, which then is the base again
	tab.send(type="resend", id=raw["id"])
	resent = tab.receive()
	assert resent["type"] == "update" and "patched" not in resent
	assert resent["version"] == raw["version"]
	assert "Message number 101" in resent["html"]

	say(102)
	assert tab.receive()["patched"]
	tab.close()


def test_resend_for_something_never_sent_is_ignored(asgi_server):

	server = asgi_server(make_app())
	page_id, _ = load(server)
	tab = Tab(server, page_id)

	tab.send(type="resend", id="nope")
	tab.send(type="resend", id=None)
	tab.nothing()
	tab.close()


def test_a_new_page_on_the_socket_starts_patches_afresh(asgi_server):

	server = asgi_server(make_app())
	page_id, _ = load(server)
	tab = Tab(server, page_id)
	say(100)
	tab.receive()

	# Navigation: the same socket says hello for another page, and core.js forgets its bases
	other, _ = load(server)
	tab.send(type="hello", page_id=other, patch=True)
	assert tab.receive() == {"type": "ready"}
	tab.bases.clear()

	say(101)
	assert "patched" not in tab.receive()
	say(102)
	assert tab.receive()["patched"]
	tab.close()


# Hidden tabs


def test_a_hidden_tab_gets_no_pushes_and_its_page_renders_nothing(asgi_server):

	app = make_app()
	server = asgi_server(app)
	page_id, _ = load(server)
	tab = Tab(server, page_id)

	tab.send(type="pause")
	time.sleep(0.2)
	app.renders.clear()
	for number in range(100, 105):
		say(number)
	tab.nothing()
	assert app.renders == []

	# Shown again: one update with everything, from one render
	tab.send(type="resume")
	update = tab.receive()
	tab.nothing()
	tab.close()

	assert len(app.renders) == 1
	assert update["type"] == "update"
	assert all(f"Message number {number}" in update["html"] for number in range(100, 105))


def test_only_hidden_tabs_are_paused(asgi_server):

	app = make_app()
	server = asgi_server(app)
	hidden_id, _ = load(server)
	shown_id, _ = load(server)
	hidden, shown = Tab(server, hidden_id), Tab(server, shown_id)

	hidden.send(type="pause")
	time.sleep(0.2)
	app.renders.clear()
	say(100)
	assert "Message number 100" in shown.receive()["html"]
	say(101)
	assert "Message number 101" in shown.receive()["html"]
	hidden.nothing()
	assert len(app.renders) == 2

	hidden.close()
	shown.close()


def test_an_event_from_a_hidden_tab_catches_it_up_first(asgi_server):

	server = asgi_server(make_app())
	page_id, (clear,) = load(server)
	tab = Tab(server, page_id)

	tab.send(type="pause")
	time.sleep(0.2)
	say(100)
	tab.nothing()

	tab.send(type="event", ref=1, page_id=page_id, event_id=clear, data={})
	received = [tab.receive(), tab.receive()]
	tab.close()

	update = next(message for message in received if message["type"] == "update")
	result = next(message for message in received if message["type"] == "result")
	assert "Message number 100" in update["html"]
	assert result["status"] == 200 and result["version"] > update["version"]


def test_a_new_socket_for_a_paused_page_catches_it_up(asgi_server):

	server = asgi_server(make_app())
	page_id, _ = load(server)
	tab = Tab(server, page_id)
	tab.send(type="pause")
	time.sleep(0.2)
	tab.close()

	say(100)
	tab = Tab(server, page_id)
	update = tab.receive()
	tab.close()

	assert "Message number 100" in update["html"]


def test_pause_and_resume_on_the_page():

	app = make_app()
	client = app.test_client()
	client.get("/")
	page = next(iter(app.page_store.pages.values()))
	stream = page.open_stream()

	page.pause()
	app.renders.clear()
	for number in range(100, 110):
		say(number)

	assert app.renders == []
	assert page.pull(stream, 0) == []
	assert len(page.dirty) == 1

	page.resume()
	updates = page.pull(stream, 0)

	assert len(app.renders) == 1
	assert len(updates) == 1 and "Message number 109" in updates[0]["html"]
	assert not page.paused and not page.dirty

	# Nothing more to do once resumed
	page.resume()
	assert len(app.renders) == 1


def test_messages_before_the_hello_are_ignored(asgi_server):

	server = asgi_server(make_app())

	with websockets_client.connect(server.ws_url, open_timeout=5) as ws:
		ws.send(json.dumps({"type": "pause"}))
		ws.send(json.dumps({"type": "resume"}))
		ws.send(json.dumps({"type": "resend", "id": "x"}))
		page_id, _ = load(server)
		ws.send(json.dumps({"type": "hello", "page_id": page_id}))
		assert json.loads(ws.recv(5)) == {"type": "ready"}


# Compression


def test_compression_setting_reaches_uvicorn(monkeypatch, tmp_path):

	import uvicorn

	from domino import asgi

	calls = []
	monkeypatch.setattr(uvicorn, "run", lambda target, **options: calls.append(options))

	app = Domino(__name__, root_path=str(tmp_path))
	asgi.serve(app, "127.0.0.1", 0)
	app.config["DOMINO_WS_COMPRESSION"] = False
	asgi.serve(app, "127.0.0.1", 0)

	(tmp_path / "settings.json").write_text(json.dumps({"domino": {"ws_compression": False}}))
	asgi.serve(Domino(__name__, root_path=str(tmp_path)), "127.0.0.1", 0)

	assert [options["ws_per_message_deflate"] for options in calls] == [True, False, False]


def test_without_compression_the_socket_has_no_deflate(asgi_server, monkeypatch):

	import uvicorn

	from conftest import ASGIServer

	# What asgi.serve passes uvicorn, here for the test server's config
	real = uvicorn.Config
	with monkeypatch.context() as patched:
		patched.setattr(uvicorn, "Config", lambda *args, **kwargs: real(*args, ws_per_message_deflate=False, **kwargs))
		server = ASGIServer(make_app())

	try:
		with websockets_client.connect(server.ws_url, open_timeout=5, compression="deflate") as ws:
			assert ws.response.headers.get("Sec-WebSocket-Extensions") is None
		with websockets_client.connect(asgi_server(make_app()).ws_url, open_timeout=5, compression="deflate") as ws:
			assert "permessage-deflate" in ws.response.headers.get("Sec-WebSocket-Extensions")
	finally:
		server.stop()
