"""Gzip for pages, the script, other text responses and Server-Sent Event streams (#71)."""

import gzip
import http.client
import json
import threading
import zlib
from pathlib import Path

import pytest
from flask import jsonify, send_file

import domino.tags as t
from domino import Domino
from domino.compression import GzipStream, accepts_gzip, compressible
from domino.components import Document


GZIP = {"Accept-Encoding": "gzip, deflate, br"}

CORE_JS = (Path(__file__).parent.parent / "domino" / "core.js").read_text(encoding="utf-8")


class Counter(t.div):


	def __init__(self, *args, **kwargs):

		super().__init__(*args, **kwargs)

		self.count = 0


	def render(self):

		self([
			t.p() [
				f"Count: {self.count}"
			],
			t.ul()([t.li() [f"Item {number}"] for number in range(200)]),
			button := t.button() [
				"+"
			],
		])

		# An event keeps the page, so it has a stream
		button.bind("click", self.increment)


	def increment(self):

		self.count += 1


def make_app(counter=None, **settings):

	app = Domino(__name__)
	app.config["DOMINO_KEEPALIVE"] = 0.05
	app.config.update(settings)

	@app.route("/")
	def index():
		return Document() [
			Counter() if counter is None else counter  # an empty element is falsy
		]

	@app.route("/small")
	def small():
		return jsonify(ok=True)

	@app.route("/data")
	def data():
		return jsonify(items=[f"item {number}" for number in range(500)])

	@app.route("/already")
	def already():
		return gzip.compress(b"x" * 5000), 200, {"Content-Encoding": "gzip", "Content-Type": "text/plain"}

	@app.route("/file")
	def file():
		return send_file(Path(__file__), mimetype="text/plain")

	@app.route("/tagged")
	def tagged():
		response = jsonify(items=["x" * 50] * 100)
		response.set_etag("v1")
		return response

	return app


def page_id(html):

	return html.split('data-domino-page="')[1].split('"')[0]


@pytest.mark.parametrize("header, expected", [
	("gzip", True),
	("gzip, deflate, br", True),
	("br;q=1.0, GZIP;q=0.5", True),
	("x-gzip", True),
	("*", True),
	("gzip;q=0", False),
	("gzip; q=0.0, *", False),
	("*;q=0", False),
	("identity", False),
	("deflate, br", False),
	("", False),
	(None, False),
])
def test_accept_encoding_is_read_with_its_q_values(header, expected):

	assert accepts_gzip(header) is expected


def test_only_text_is_compressible():

	for mimetype in ("text/html", "text/css", "application/javascript", "application/json", "image/svg+xml", "application/ld+json"):
		assert compressible(mimetype), mimetype
	for mimetype in ("image/png", "application/octet-stream", "text/event-stream", None):
		assert not compressible(mimetype), mimetype


def test_pages_are_gzipped_when_the_browser_accepts_it():

	client = make_app().test_client()

	plain = client.get("/")
	assert "Content-Encoding" not in plain.headers
	assert plain.headers["Vary"] == "Accept-Encoding"

	response = client.get("/", headers=GZIP)
	assert response.status_code == 200
	assert response.headers["Content-Encoding"] == "gzip"
	assert response.headers["Vary"] == "Accept-Encoding"
	assert int(response.headers["Content-Length"]) == len(response.data)
	html = gzip.decompress(response.data).decode()
	assert "Item 199" in html
	assert len(response.data) * 3 < len(html)


@pytest.mark.parametrize("header", ["identity", "gzip;q=0", "deflate"])
def test_pages_are_not_gzipped_when_the_browser_refuses_it(header):

	response = make_app().test_client().get("/", headers={"Accept-Encoding": header})

	assert "Content-Encoding" not in response.headers
	assert "Item 199" in response.get_data(as_text=True)


def test_the_core_script_is_gzipped():

	client = make_app().test_client()

	response = client.get("/_domino/core", headers=GZIP)
	assert response.headers["Content-Encoding"] == "gzip"
	assert response.headers["Vary"] == "Accept-Encoding"
	assert gzip.decompress(response.data).decode() == CORE_JS
	assert len(response.data) * 3 < len(CORE_JS.encode())

	plain = client.get("/_domino/core")
	assert "Content-Encoding" not in plain.headers
	assert plain.get_data(as_text=True) == CORE_JS


def test_other_text_responses_are_gzipped_too():

	client = make_app().test_client()

	response = client.get("/data", headers=GZIP)
	assert response.headers["Content-Encoding"] == "gzip"
	assert json.loads(gzip.decompress(response.data))["items"][499] == "item 499"


def test_small_streamed_and_already_encoded_responses_are_left_alone():

	client = make_app().test_client()

	small = client.get("/small", headers=GZIP)
	assert "Content-Encoding" not in small.headers
	assert small.get_json() == {"ok": True}

	already = client.get("/already", headers=GZIP)
	assert already.headers["Content-Encoding"] == "gzip"
	assert gzip.decompress(already.data) == b"x" * 5000

	# send_file() bodies are left to a proxy or CDN
	file = client.get("/file", headers=GZIP)
	assert "Content-Encoding" not in file.headers
	assert file.data == Path(__file__).read_bytes()
	file.close()


def test_a_strong_etag_becomes_weak_once_gzipped():

	client = make_app().test_client()

	response = client.get("/tagged", headers=GZIP)
	assert response.headers["Content-Encoding"] == "gzip"
	assert response.headers["ETag"] == 'W/"v1"'

	assert client.get("/tagged").headers["ETag"] == '"v1"'


def test_the_setting_turns_it_off(tmp_path):

	(tmp_path / "settings.json").write_text(json.dumps({"domino": {"compression": False}}))
	app = Domino(__name__, root_path=str(tmp_path))
	assert app.config["DOMINO_COMPRESSION"] is False

	client = make_app(DOMINO_COMPRESSION=False).test_client()
	for path in ("/", "/_domino/core", "/data"):
		assert "Content-Encoding" not in client.get(path, headers=GZIP).headers, path


def test_a_gzip_stream_can_be_read_chunk_by_chunk():

	stream = GzipStream()
	reader = zlib.decompressobj(16 + zlib.MAX_WBITS)

	# Each chunk decompresses whole as soon as it arrives, so updates aren't held back
	for text in (b": open\n\n", b"data: {}\n\n" * 50, b": keepalive\n\n"):
		assert reader.decompress(stream.chunk(text)) == text

	assert reader.decompress(stream.end()) == b""
	assert reader.eof


def read_gzip_stream(response, count, timeout=5):

	# Read in a thread so a broken stream fails the test instead of hanging it
	reader = zlib.decompressobj(16 + zlib.MAX_WBITS)
	chunks = []

	def read():
		for chunk in response.response:
			chunks.append(reader.decompress(chunk).decode())
			if len(chunks) == count:
				break

	thread = threading.Thread(target=read, daemon=True)
	thread.start()
	thread.join(timeout)
	assert not thread.is_alive(), f"stream stalled after {chunks!r}"
	response.close()

	return chunks


def test_server_sent_events_are_gzipped_as_they_go():

	counter = Counter()
	app = make_app(counter)
	client = app.test_client()
	page = page_id(client.get("/").get_data(as_text=True))

	response = client.get(f"/_domino/stream?page={page}", headers=GZIP, buffered=False)
	assert response.status_code == 200
	assert response.mimetype == "text/event-stream"
	assert response.headers["Content-Encoding"] == "gzip"

	counter.count = 3
	counter.refresh()

	opened, update, keepalive = read_gzip_stream(response, 3)
	assert opened == ": open\n\n"
	assert "Count: 3" in json.loads(update[len("data: "):])["html"]
	assert keepalive == ": keepalive\n\n"


def test_server_sent_events_stay_plain_without_accept_encoding():

	app = make_app()
	client = app.test_client()
	page = page_id(client.get("/").get_data(as_text=True))

	response = client.get(f"/_domino/stream?page={page}", buffered=False)
	assert "Content-Encoding" not in response.headers
	assert next(iter(response.response)) == b": open\n\n"
	response.close()


# Over ASGI (uvicorn) ------------------------------------------------------------------------------


def get(server, path, headers):

	connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
	connection.request("GET", path, headers=headers)

	return connection, connection.getresponse()


def test_pages_and_the_script_are_gzipped_over_asgi(asgi_server):

	server = asgi_server(make_app())

	connection, response = get(server, "/", GZIP)
	assert response.getheader("Content-Encoding") == "gzip"
	html = gzip.decompress(response.read()).decode()
	assert "Item 199" in html
	connection.close()

	connection, response = get(server, "/_domino/core", GZIP)
	assert response.getheader("Content-Encoding") == "gzip"
	assert gzip.decompress(response.read()).decode() == CORE_JS
	connection.close()

	connection, response = get(server, "/", {})
	assert response.getheader("Content-Encoding") is None
	assert "Item 199" in response.read().decode()
	connection.close()


def test_server_sent_events_are_gzipped_over_asgi(asgi_server):

	counter = Counter()
	app = make_app(counter)
	server = asgi_server(app)
	connection, response = get(server, "/", {})
	page = page_id(response.read().decode())
	connection.close()

	connection, response = get(server, f"/_domino/stream?page={page}", {"Accept-Encoding": "gzip"})
	assert response.status == 200
	assert response.getheader("Content-Encoding") == "gzip"
	assert response.getheader("Vary") == "Accept-Encoding"

	reader = zlib.decompressobj(16 + zlib.MAX_WBITS)
	received = ""

	def until(text):
		nonlocal received
		while text not in received:
			received += reader.decompress(response.read1(65536)).decode()

	until(": open\n\n")
	counter.count = 4
	counter.refresh()
	until("Count: 4")
	until(": keepalive\n\n")
	connection.close()


def test_server_sent_events_stay_plain_over_asgi_without_accept_encoding(asgi_server):

	server = asgi_server(make_app())
	connection, response = get(server, "/", {})
	page = page_id(response.read().decode())
	connection.close()

	connection, response = get(server, f"/_domino/stream?page={page}", {"Accept-Encoding": "identity"})
	assert response.getheader("Content-Encoding") is None
	assert response.readline() == b": open\n"
	connection.close()
