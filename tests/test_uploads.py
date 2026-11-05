"""File uploads: files go up in a multipart POST to /_domino/upload, which answers with a token
per file; the event carries the tokens and its handler gets the files as event.files."""

import json
import time
import urllib.error
import urllib.request
from io import BytesIO

import pytest
from werkzeug.datastructures import FileStorage
from werkzeug.test import encode_multipart

import domino.tags as t
from domino import Domino
from domino import _optimistic as optimistic
from domino import Document
from domino.testing import DominoTestError


class Avatar(t.div):


	def __init__(self, *args, **kwargs):

		super().__init__(*args, **kwargs)

		self.received = []  # the files of each event
		self.text = ""


	def render(self):

		self([
			t.form(on_submit=self.save) [
				t.input(type="file", name="photo"),
				t.input(type="file", name="photos", multiple=True),
				t.input(name="caption"),
				t.button() [
					"Upload"
				]
			],
			t.input(type="file", name="quick", on_change=self.quick),
			t.button(on_click=self.click) [
				"plain"
			],
			t.p() [
				self.text
			]
		])


	def save(self, event):

		self.received.append(event.files)
		photo = event.files.get("photo")
		names = ",".join(file.filename for file in event.files.getlist("photos"))
		self.text = f"{photo and photo.filename} {photo and photo.read()!r} {photo and photo.size} {names} {event.form.get('caption')}"

		return self


	def quick(self, event):

		self.received.append(event.files)
		file = event.files["quick"]
		self.text = f"quick {file.filename} {file.content_type} {file.read()!r}"

		return self


	def click(self, event):

		self.received.append(event.files)

		return self


def make_app():

	app = Domino(__name__)
	app.testing = True
	avatar = Avatar()

	@app.route("/")
	def index():
		return Document() [
			avatar
		]

	return app, avatar


def load(client):

	html = client.get("/").get_data(as_text=True)
	page_id = html.split('data-domino-page="')[1].split('"')[0]
	event_ids = [part.split('"')[0] for part in html.split('data-event-id="')[1:]]

	return page_id, event_ids


def upload(client, page_id, files, headers=None):

	headers = {"X-Domino-Page": page_id} if headers is None else headers

	return client.post("/_domino/upload", data=files, headers=headers)


def send(client, page_id, event_id, data):

	return client.post("/_domino/events", json={"page_id": page_id, "event_id": event_id, "data": data})


def test_upload_gives_tokens_that_the_event_swaps_for_files():

	app, avatar = make_app()
	client = app.test_client()
	page_id, (submit, *_) = load(client)

	response = upload(client, page_id, {"photo": (BytesIO(b"hello"), "a.txt", "text/plain")})
	assert response.status_code == 200
	tokens = response.get_json()["files"]
	assert list(tokens) == ["photo"] and len(tokens["photo"]) == 1

	result = send(client, page_id, submit, {"form": {"caption": "hi"}, "files": tokens})

	assert result.status_code == 200
	assert "a.txt b&#39;hello&#39; 5  hi" in result.get_json()["html"]
	(files,) = avatar.received
	assert files["photo"].content_type == "text/plain"


def test_several_files_under_one_name():

	app, avatar = make_app()
	client = app.test_client()
	page_id, (submit, *_) = load(client)

	tokens = upload(client, page_id, {"photos": [(BytesIO(b"1"), "one.txt"), (BytesIO(b"2"), "two.txt")]}).get_json()["files"]
	send(client, page_id, submit, {"files": tokens})

	files = avatar.received[0]
	assert [file.filename for file in files.getlist("photos")] == ["one.txt", "two.txt"]
	assert "photo" not in files


def test_events_without_files_get_an_empty_multidict():

	app, avatar = make_app()
	client = app.test_client()
	page_id, (_, _, click) = load(client)

	assert send(client, page_id, click, {}).status_code == 200
	assert len(avatar.received[0]) == 0
	assert avatar.received[0].getlist("photos") == []


def test_tokens_work_once():

	app, _ = make_app()
	client = app.test_client()
	page_id, (submit, *_) = load(client)

	tokens = upload(client, page_id, {"photo": (BytesIO(b"x"), "a.txt")}).get_json()["files"]

	assert send(client, page_id, submit, {"files": tokens}).status_code == 200
	again = send(client, page_id, submit, {"files": tokens})
	assert again.status_code == 400
	assert again.get_json() == {"error": "Unknown or expired upload"}


def test_another_pages_tokens_are_refused_and_left_for_it():

	app, avatar = make_app()
	client = app.test_client()
	page_id, (submit, *_) = load(client)
	other_id, _ = load(client)

	tokens = upload(client, other_id, {"photo": (BytesIO(b"x"), "a.txt")}).get_json()["files"]

	assert send(client, page_id, submit, {"files": tokens}).status_code == 400
	assert avatar.received == []
	assert len(app.uploads) == 1


def test_unclaimed_uploads_expire_and_are_deleted():

	app, _ = make_app()
	client = app.test_client()
	page_id, (submit, *_) = load(client)
	app.config["DOMINO_UPLOAD_TTL"] = 0.05

	tokens = upload(client, page_id, {"photo": (BytesIO(b"x"), "a.txt")}).get_json()["files"]
	(_, _, file), = app.uploads.files.values()
	time.sleep(0.1)

	assert send(client, page_id, submit, {"files": tokens}).status_code == 400
	assert len(app.uploads) == 0
	assert file.closed


def test_files_are_deleted_once_the_event_is_handled():

	app, avatar = make_app()
	client = app.test_client()
	page_id, (submit, *_) = load(client)

	# Over 500 KB, so it's spooled to a temporary file rather than held in memory
	tokens = upload(client, page_id, {"photo": (BytesIO(b"x" * 600_000), "big.bin")}).get_json()["files"]
	(_, _, file), = app.uploads.files.values()
	assert file.stream._rolled

	send(client, page_id, submit, {"files": tokens})

	assert avatar.received[0]["photo"] is file
	assert file.closed
	assert len(app.uploads) == 0


def test_files_of_an_unknown_event_are_deleted_too():

	app, _ = make_app()
	client = app.test_client()
	page_id, _ = load(client)

	tokens = upload(client, page_id, {"photo": (BytesIO(b"x"), "a.txt")}).get_json()["files"]
	(_, _, file), = app.uploads.files.values()

	assert send(client, page_id, "event-nope-submit", {"files": tokens}).status_code == 404
	assert file.closed


def test_uploads_need_the_page_header_so_other_sites_cant_post_them():

	app, _ = make_app()
	client = app.test_client()
	page_id, _ = load(client)

	# What a form on another site could send: multipart, but no custom header
	refused = upload(client, page_id, {"photo": (BytesIO(b"x"), "a.txt")}, headers={})
	unknown = upload(client, "nope", {"photo": (BytesIO(b"x"), "a.txt")})

	assert refused.status_code == 403
	assert unknown.status_code == 404
	assert len(app.uploads) == 0


def test_uploads_over_the_limit_are_refused():

	app, _ = make_app()
	client = app.test_client()
	page_id, _ = load(client)
	app.config["DOMINO_MAX_UPLOAD_MB"] = 0.01

	response = upload(client, page_id, {"photo": (BytesIO(b"x" * 20_000), "big.bin")})

	assert response.status_code == 413
	assert response.get_json() == {"error": "Upload too large: the limit is 0.01 MB", "debug": True}
	assert len(app.uploads) == 0


def test_the_limit_is_checked_while_reading_when_the_size_isnt_known():

	app, _ = make_app()
	client = app.test_client()
	page_id, _ = load(client)
	app.config["DOMINO_MAX_UPLOAD_MB"] = 0.01

	# Chunked: no Content-Length up front (the server marks such a body as terminated)
	boundary, body = encode_multipart({"photo": FileStorage(BytesIO(b"x" * 20_000), "big.bin")})
	response = client.post("/_domino/upload", input_stream=BytesIO(body), environ_overrides={"wsgi.input_terminated": True}, headers={
		"X-Domino-Page": page_id,
		"Content-Type": f"multipart/form-data; boundary={boundary}",
		"Transfer-Encoding": "chunked",
	})

	assert response.status_code == 413
	assert len(app.uploads) == 0


def test_the_limit_comes_from_the_settings(tmp_path):

	(tmp_path / "settings.json").write_text('{"domino": {"max_upload_mb": 2}}')
	app = Domino(__name__, settings=str(tmp_path / "settings.json"))

	assert app.config["DOMINO_MAX_UPLOAD_MB"] == 2


def test_handlers_using_files_are_never_predicted():

	class Uploader(t.div):

		from domino import State
		count = State(0)

		def keep(self, event):
			self.count = len(event.files.getlist("photos"))

		def bump(self, event):
			self.count += 1

	assert optimistic.predictable_methods(Uploader) == {"bump"}


# The simulated browser (domino.testing), and so the page fixture


def test_test_page_uploads_with_the_form_and_clears_it():

	app, _ = make_app()
	page = app.test_page("/")

	page.upload("input[name=photo]", ("a.txt", b"hello", "text/plain"))
	page.upload("input[name=photos]", ("one.txt", b"1"), ("two.txt", "2"))
	page.fill("input[name=caption]", "hi")
	page.click("button", text="Upload")

	assert page.text("p") == "a.txt b'hello' 5 one.txt,two.txt hi"
	assert page.find("input[name=photo]").files is None
	assert len(app.uploads) == 0


def test_test_page_uploads_on_change_from_a_path(tmp_path):

	app, _ = make_app()
	page = app.test_page("/")
	path = tmp_path / "notes.txt"
	path.write_bytes(b"from disk")

	page.upload("input[name=quick]", path)

	assert page.text("p") == "quick notes.txt text/plain b'from disk'"


def test_test_page_upload_needs_a_file_input_and_multiple_for_several():

	app, _ = make_app()
	page = app.test_page("/")

	with pytest.raises(DominoTestError, match="isn't a file input"):
		page.upload("input[name=caption]", ("a.txt", b"x"))
	with pytest.raises(DominoTestError, match="takes one file"):
		page.upload("input[name=photo]", ("a.txt", b"x"), ("b.txt", b"y"))


def test_test_page_reports_a_refused_upload():

	app, _ = make_app()
	page = app.test_page("/")
	app.config["DOMINO_MAX_UPLOAD_MB"] = 0.01

	with pytest.raises(DominoTestError, match="Upload too large"):
		page.upload("input[name=quick]", ("big.bin", b"x" * 20_000))


def test_clicks_inside_a_form_upload_nothing():

	app, avatar = make_app()
	page = app.test_page("/")

	page.upload("input[name=photo]", ("a.txt", b"x"))
	page.click("button", text="plain")

	assert len(avatar.received[0]) == 0
	assert len(app.uploads) == 0


# Over ASGI: the upload is an HTTP POST and the event goes over the WebSocket


def test_upload_over_http_then_event_over_the_websocket(asgi_server):

	websockets_client = pytest.importorskip("websockets.sync.client")

	app, avatar = make_app()
	server = asgi_server(app)
	html = urllib.request.urlopen(server.url).read().decode()
	page_id = html.split('data-domino-page="')[1].split('"')[0]
	submit = html.split('data-event-id="')[1].split('"')[0]

	boundary, body = encode_multipart({"photo": FileStorage(BytesIO(b"over asgi"), "a.txt")})
	request = urllib.request.Request(server.url + "_domino/upload", data=body, method="POST", headers={
		"Content-Type": f"multipart/form-data; boundary={boundary}",
		"X-Domino-Page": page_id,
	})
	tokens = json.loads(urllib.request.urlopen(request).read())["files"]

	with websockets_client.connect(server.ws_url, open_timeout=5) as ws:
		ws.send(json.dumps({"type": "hello", "page_id": page_id}))
		assert json.loads(ws.recv(5)) == {"type": "ready"}
		ws.send(json.dumps({"type": "event", "ref": 1, "page_id": page_id, "event_id": submit, "data": {"files": tokens}}))
		result = json.loads(ws.recv(5))

	assert result["status"] == 200
	assert "a.txt b&#39;over asgi&#39; 9" in result["html"]
	assert avatar.received[0]["photo"].closed

	# And the header is required there too
	refused = urllib.request.Request(server.url + "_domino/upload", data=b"", method="POST", headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
	with pytest.raises(urllib.error.HTTPError) as error:
		urllib.request.urlopen(refused)
	assert error.value.code == 403
