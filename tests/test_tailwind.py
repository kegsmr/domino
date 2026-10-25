"""Tailwind CSS with zero setup (domino.tailwind), with a fake CLI so nothing is downloaded."""

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import textwrap
import time
import urllib.error
from pathlib import Path

import pytest

import domino.cli as cli
import domino.tags as t
from domino import Domino, tailwind, template
from domino.components import Document

from conftest import EXAMPLES, running, wait_until


# Stands in for Tailwind's CLI: writes a rule for each "tw-..." word in the app's .py and .html
# files, says whether it minified, and with --watch rebuilds when they change until stdin closes
FAKE_CLI = '''\
import os, re, sys, threading, time

args = sys.argv[1:]
if "--help" in args:
	print("tailwindcss v0.0.0 (fake)")
	sys.exit(0)

def option(name):
	return args[args.index(name) + 1]

source, output = option("--input"), option("--output")

def sources():
	for folder, folders, files in os.walk("."):
		folders[:] = [name for name in folders if not name.startswith(".")]
		for name in files:
			if name.endswith((".py", ".html")):
				yield os.path.join(folder, name)

def build():
	words = set()
	for path in sources():
		with open(path, encoding="utf-8") as file:
			words.update(re.findall(r"\\btw-[a-z0-9-]+", file.read()))
	with open(source, encoding="utf-8") as file:
		header = "/* input: " + file.read().replace("*/", "") + " */"
	if "--minify" in args:
		header = "/*minified*/"
	with open(output, "w", encoding="utf-8") as file:
		file.write(header + "\\n" + "\\n".join(f".{word}{{color:rgb(255, 0, 0)}}" for word in sorted(words)) + "\\n")

def stamps():
	return sorted((path, os.stat(path).st_mtime_ns) for path in sources())

build()
if "--watch" in args:
	with open(output + ".pid", "w") as file:
		file.write(str(os.getpid()))
	# Like the real one: stops when its stdin closes
	threading.Thread(target=lambda: (sys.stdin.read(), os._exit(0)), daemon=True).start()
	seen = stamps()
	while True:
		time.sleep(0.05)
		if stamps() != seen:
			seen = stamps()
			build()
'''


def write_fake_cli(folder):

	path = Path(folder) / "fake-tailwindcss"
	path.write_text(f"#!{sys.executable}\n" + FAKE_CLI, encoding="utf-8")
	path.chmod(0o755)

	return path


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
	"""A DOMINO_HOME of its own, so nothing is read from or downloaded into ~/.domino."""

	monkeypatch.delenv(tailwind.ENV_BIN, raising=False)
	monkeypatch.setenv("DOMINO_HOME", str(tmp_path / "home"))

	return tmp_path / "home"


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):

	path = write_fake_cli(tmp_path)
	monkeypatch.setenv(tailwind.ENV_BIN, str(path))

	return path


@pytest.fixture
def stop_watchers():

	yield
	tailwind.stop_all()


def make_app(folder, settings=None, files=None):

	folder.mkdir(parents=True, exist_ok=True)
	if settings is not None:
		(folder / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
	for name, text in (files or {}).items():
		(folder / name).parent.mkdir(parents=True, exist_ok=True)
		(folder / name).write_text(text, encoding="utf-8")

	return Domino(__name__, root_path=str(folder), pages=False)


# Turning it on


def test_off_unless_asked(tmp_path):

	assert tailwind.options({}, tmp_path) is None
	assert tailwind.options({"tailwind": False}, tmp_path) is None
	assert make_app(tmp_path / "app").tailwind is None


def test_the_setting_turns_it_on_with_the_generated_input(tmp_path):

	options = tailwind.options({"tailwind": True}, tmp_path)

	assert options == {"version": tailwind.DEFAULT_VERSION, "input": None, "output": tmp_path.resolve() / ".domino" / "tailwind.css"}


def test_a_tailwind_css_in_the_app_folder_turns_it_on(tmp_path):

	(tmp_path / "tailwind.css").write_text('@import "tailwindcss";\n')

	assert tailwind.options({}, tmp_path)["input"] == tmp_path.resolve() / "tailwind.css"
	assert tailwind.options({"tailwind": True}, tmp_path)["input"] == tmp_path.resolve() / "tailwind.css"
	# The setting still wins
	assert tailwind.options({"tailwind": False}, tmp_path) is None


def test_version_and_input_settings(tmp_path):

	options = tailwind.options({"tailwind": {"version": "v4.1.0", "input": "styles/main.css"}}, tmp_path)

	assert options["version"] == "4.1.0"
	assert options["input"] == tmp_path.resolve() / "styles" / "main.css"


def test_the_environment_turns_it_on(tmp_path, monkeypatch):

	monkeypatch.setenv("DOMINO_TAILWIND", "true")

	assert make_app(tmp_path / "app").tailwind is not None


# The input


def test_generated_input_scans_the_app_folder_but_not_dot_domino(tmp_path):

	path = tailwind.input_file(tmp_path, tailwind.options({"tailwind": True}, tmp_path))
	text = path.read_text()

	assert path == tmp_path.resolve() / ".domino" / "tailwind.input.css"
	assert '@import "tailwindcss" source(none);' in text
	assert '@source "../**/*.{py,html}";' in text
	assert '@source not "../.domino";' in text


def test_generated_input_is_only_written_when_it_changes(tmp_path):

	options = tailwind.options({"tailwind": True}, tmp_path)
	path = tailwind.input_file(tmp_path, options)
	os.utime(path, ns=(1, 1))

	tailwind.input_file(tmp_path, options)

	assert path.stat().st_mtime_ns == 1


def test_the_app_input_is_used_as_it_is(tmp_path):

	(tmp_path / "tailwind.css").write_text('@import "tailwindcss";\n@theme { --color-brand: #f60; }\n')

	path = tailwind.input_file(tmp_path, tailwind.options({}, tmp_path))

	assert path == tmp_path.resolve() / "tailwind.css"
	assert not (tmp_path / ".domino").exists()


def test_a_missing_input_setting_is_a_clear_error(tmp_path):

	with pytest.raises(tailwind.TailwindError, match="No Tailwind CSS input at .*missing.css"):
		tailwind.input_file(tmp_path, tailwind.options({"tailwind": {"input": "missing.css"}}, tmp_path))


# The link in every page's head


class Card(t.div):

	css = {"padding": "1rem"}


def pages_app(folder, settings={"tailwind": True}):

	app = make_app(folder, settings, {"home.html": "<html><head><title>Jinja</title><style>p { margin: 0 }</style></head><body>{{ component(Card) }}</body></html>"})

	@app.route("/document")
	def document():
		page = Document(title="Document") [Card()]
		page.style("body", margin=0)
		return page

	@app.route("/head")
	def head():
		return t.html() [
			t.head() [t.title() ["By hand"]],
			t.body() [Card()]
		]

	@app.route("/jinja")
	def jinja():
		return template("home.html", Card=Card)

	return app


@pytest.mark.parametrize("path", ["/document", "/head", "/jinja"])
def test_every_kind_of_page_links_the_css_before_its_own_styles(tmp_path, path):

	html = pages_app(tmp_path).test_client().get(path).get_data(as_text=True)

	link = '<link rel="stylesheet" href="/_domino/tailwind.css" data-domino-tailwind>'
	assert html.count("data-domino-tailwind") == 1
	assert link in html
	assert html.index(link) < html.index("</head>")
	# Before the component CSS and the page's own styles (though Tailwind's layers lose to them anyway)
	assert html.index(link) < html.index(".Card")
	assert html.index(link) < html.index("<style", html.index("<head"))


@pytest.mark.parametrize("path", ["/document", "/head", "/jinja"])
def test_no_link_when_tailwind_is_off(tmp_path, path):

	html = pages_app(tmp_path, settings={}).test_client().get(path).get_data(as_text=True)

	assert "tailwind" not in html


def test_the_link_names_the_built_css_by_its_hash(tmp_path):

	app = pages_app(tmp_path)
	output = tmp_path / ".domino" / "tailwind.css"
	output.parent.mkdir()
	output.write_text(".p-4{padding:1rem}")
	digest = hashlib.sha256(output.read_bytes()).hexdigest()[:12]

	html = app.test_client().get("/document").get_data(as_text=True)

	assert f'href="/_domino/tailwind.css?v={digest}"' in html


def test_debug_pages_listen_for_rebuilds(tmp_path):

	app = pages_app(tmp_path)

	assert "data-domino-watch" not in app.test_client().get("/document").get_data(as_text=True)

	app.debug = True
	assert "data-domino-tailwind data-domino-watch>" in app.test_client().get("/document").get_data(as_text=True)


def test_event_responses_dont_carry_the_link(tmp_path):

	app = pages_app(tmp_path)

	assert tailwind.link() == ""
	with app.test_request_context():
		assert "data-domino-tailwind" in tailwind.link()
		assert "data-domino-tailwind" not in Card()._render()


# Serving the CSS


def built_app(tmp_path, text=".p-4{padding:1rem}"):

	app = make_app(tmp_path / "app", {"tailwind": True})
	output = tmp_path / "app" / ".domino" / "tailwind.css"
	output.parent.mkdir()
	output.write_text(text)

	return app, hashlib.sha256(text.encode()).hexdigest()[:12]


def test_the_css_is_cached_forever_under_its_hash(tmp_path):

	app, digest = built_app(tmp_path)
	client = app.test_client()

	response = client.get(f"/_domino/tailwind.css?v={digest}")

	assert response.status_code == 200
	assert response.mimetype == "text/css"
	assert response.get_data(as_text=True) == ".p-4{padding:1rem}"
	assert response.headers["Cache-Control"] == "public, max-age=31536000, immutable"


def test_other_urls_for_the_css_are_revalidated(tmp_path):

	app, digest = built_app(tmp_path)
	client = app.test_client()

	assert client.get("/_domino/tailwind.css").headers["Cache-Control"] == "no-cache"
	assert client.get("/_domino/tailwind.css?v=old").headers["Cache-Control"] == "no-cache"

	etag = client.get("/_domino/tailwind.css").headers["ETag"]
	assert client.get("/_domino/tailwind.css", headers={"If-None-Match": etag}).status_code == 304


def test_unbuilt_css_is_a_404_saying_how_to_build_it(tmp_path, capsys):

	app = make_app(tmp_path / "app", {"tailwind": True})

	response = app.test_client().get("/_domino/tailwind.css")

	assert response.status_code == 404
	assert "domino tailwind build" in response.get_data(as_text=True)
	# Without debug mode nothing is downloaded on a request
	assert "isn't downloaded" in capsys.readouterr().err


def test_a_server_that_didnt_build_it_builds_it_on_the_first_request(tmp_path, fake_cli):

	app = make_app(tmp_path / "app", {"tailwind": True}, {"pages.py": 'x = "tw-lazy"'})

	response = app.test_client().get("/_domino/tailwind.css")

	assert response.status_code == 200
	assert ".tw-lazy" in response.get_data(as_text=True)
	assert "/*minified*/" in response.get_data(as_text=True)


def test_the_css_routes_only_exist_with_tailwind(tmp_path):

	client = make_app(tmp_path / "app").test_client()

	assert client.get("/_domino/tailwind.css").status_code == 404
	assert client.get("/_domino/tailwind/watch").status_code == 404


def test_the_watch_stream_says_the_version_and_only_in_debug(tmp_path):

	app, digest = built_app(tmp_path)

	assert app.test_client().get("/_domino/tailwind/watch").status_code == 404

	app.debug = True
	response = app.test_client().get("/_domino/tailwind/watch", buffered=False)
	chunks = iter(response.response)
	try:
		assert response.mimetype == "text/event-stream"
		assert next(chunks) == b"retry: 500\n\n"
		assert json.loads(next(chunks).decode()[len("data: "):]) == {"version": digest}

		(tmp_path / "app" / ".domino" / "tailwind.css").write_text(".p-8{padding:2rem}")
		assert json.loads(next(chunks).decode()[len("data: "):]) == {"version": tailwind.version(tmp_path / "app" / ".domino" / "tailwind.css")}
	finally:
		response.close()


def test_the_watch_socket_says_the_version_over_asgi(tmp_path, asgi_server):

	client = pytest.importorskip("websockets.sync.client")

	app, digest = built_app(tmp_path)
	app.debug = True
	server = asgi_server(app)
	output = tmp_path / "app" / ".domino" / "tailwind.css"

	with client.connect(f"ws://127.0.0.1:{server.port}/_domino/tailwind/watch") as ws:
		assert json.loads(ws.recv(5)) == {"version": digest}
		output.write_text(".p-8{padding:2rem}")
		assert json.loads(ws.recv(5)) == {"version": tailwind.version(output)}


# Building


def test_build_minifies_for_production(tmp_path, fake_cli):

	app = make_app(tmp_path / "app", {"tailwind": True}, {"pages/index.py": 'x = "tw-card tw-grid"'})

	output = tailwind.build(app.root_path, app.tailwind)

	assert output == tmp_path.resolve() / "app" / ".domino" / "tailwind.css"
	assert output.read_text().startswith("/*minified*/")
	assert ".tw-card" in output.read_text() and ".tw-grid" in output.read_text()

	tailwind.build(app.root_path, app.tailwind, minify=False)
	assert '@import "tailwindcss" source(none);' in output.read_text()


def test_build_errors_show_the_cli_output(tmp_path, monkeypatch):

	broken = tmp_path / "broken"
	broken.write_text(f"#!{sys.executable}\nimport sys\nprint('Cannot apply unknown utility class `nope`', file=sys.stderr)\nsys.exit(1)\n")
	broken.chmod(0o755)
	monkeypatch.setenv(tailwind.ENV_BIN, str(broken))

	with pytest.raises(tailwind.TailwindError, match="(?s)exit code 1.*unknown utility class"):
		tailwind.build(tmp_path, tailwind.options({"tailwind": True}, tmp_path))


def test_production_builds_with_the_cli_it_has(tmp_path, fake_cli, capsys):

	options = tailwind.options({"tailwind": True}, tmp_path)
	(tmp_path / "page.py").write_text('x = "tw-prod"')

	assert tailwind.prepare(tmp_path, options) == options["output"]
	assert ".tw-prod" in options["output"].read_text()
	assert "Tailwind CSS: built" in capsys.readouterr().err


def test_production_uses_css_built_beforehand_without_a_cli(tmp_path, monkeypatch, capsys):

	options = tailwind.options({"tailwind": True}, tmp_path)
	options["output"].parent.mkdir()
	options["output"].write_text("/*built in the image*/")
	monkeypatch.setattr(tailwind, "download", lambda *args: pytest.fail("downloaded"))

	assert tailwind.prepare(tmp_path, options) == options["output"]
	assert options["output"].read_text() == "/*built in the image*/"
	assert "built beforehand" in capsys.readouterr().err


def test_production_without_cli_or_css_logs_why(tmp_path, monkeypatch, capsys):

	def offline(url, timeout=None):
		raise urllib.error.URLError("no network")

	monkeypatch.setattr(tailwind.urllib.request, "urlopen", offline)

	assert tailwind.prepare(tmp_path, tailwind.options({"tailwind": True}, tmp_path)) is None
	assert f"set {tailwind.ENV_BIN}" in capsys.readouterr().err


def test_app_run_builds_once_in_production(tmp_path, fake_cli, monkeypatch):

	import domino.asgi
	monkeypatch.setattr(domino.asgi, "serve", lambda *args, **kwargs: None)
	app = make_app(tmp_path / "app", {"tailwind": True, "mongo": {"auto": False}})

	app.run(debug=False)

	assert app.tailwind["output"].read_text().startswith("/*minified*/")
	assert tailwind._watchers == []


# The CLI binary


def test_asset_names():

	assert tailwind.asset_name("Linux", "x86_64", musl=False) == "tailwindcss-linux-x64"
	assert tailwind.asset_name("Linux", "aarch64", musl=False) == "tailwindcss-linux-arm64"
	assert tailwind.asset_name("Linux", "x86_64", musl=True) == "tailwindcss-linux-x64-musl"
	assert tailwind.asset_name("Darwin", "arm64") == "tailwindcss-macos-arm64"
	assert tailwind.asset_name("Darwin", "x86_64") == "tailwindcss-macos-x64"
	assert tailwind.asset_name("Windows", "AMD64") == "tailwindcss-windows-x64.exe"

	with pytest.raises(tailwind.TailwindError, match=tailwind.ENV_BIN):
		tailwind.asset_name("Linux", "riscv64")


def test_checksums_are_read_from_the_release():

	sums = "aa11  ./tailwindcss-linux-arm64\nBB22  ./tailwindcss-linux-x64\n"

	assert tailwind.checksum(sums, "tailwindcss-linux-x64") == "bb22"
	assert tailwind.checksum(sums, "tailwindcss-macos-x64") is None


def test_the_env_var_points_at_a_cli(tmp_path, monkeypatch):

	monkeypatch.setenv(tailwind.ENV_BIN, str(tmp_path / "nowhere"))

	with pytest.raises(tailwind.TailwindError, match=f"{tailwind.ENV_BIN} is .*nowhere, which isn't a file"):
		tailwind.ensure_binary()


class Response:
	"""A urlopen() result."""

	def __init__(self, data):

		self.data = data
		self.headers = {"Content-Length": str(len(data))}

	def read(self, size=-1):

		chunk, self.data = (self.data, b"") if size < 0 else (self.data[:size], self.data[size:])
		return chunk

	def __enter__(self):

		return self

	def __exit__(self, *exc):

		return False


def serve_release(monkeypatch, binary, sums=None):

	asset = tailwind.asset_name()
	if sums is None:
		sums = f"{hashlib.sha256(binary).hexdigest()}  ./{asset}\n"
	urls = []

	def urlopen(url, timeout=None):
		urls.append(url)
		if url.endswith("/sha256sums.txt"):
			return Response(sums.encode())
		if url.endswith("/" + asset):
			return Response(binary)
		raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

	monkeypatch.setattr(tailwind.urllib.request, "urlopen", urlopen)

	return urls


def test_download_checks_the_checksum_and_that_it_runs_then_caches_it(home, monkeypatch, capsys):

	binary = f"#!{sys.executable}\nprint('tailwindcss v4 (fake)')\n".encode()
	urls = serve_release(monkeypatch, binary)

	path = tailwind.ensure_binary("4.9.9")

	assert path == home / "tailwind" / "4.9.9" / ("tailwindcss.exe" if os.name == "nt" else "tailwindcss")
	assert path.read_bytes() == binary
	assert os.access(path, os.X_OK)
	assert urls[0] == f"{tailwind.RELEASES_URL}/download/v4.9.9/sha256sums.txt"
	assert "Downloading Tailwind CSS 4.9.9" in capsys.readouterr().err

	# Cached: later runs work offline
	urls.clear()
	assert tailwind.ensure_binary("4.9.9") == path
	assert urls == []


def test_a_bad_checksum_leaves_nothing_behind(home, monkeypatch):

	serve_release(monkeypatch, b"#!/bin/sh\n", sums=f"{'0' * 64}  ./{tailwind.asset_name()}\n")

	with pytest.raises(tailwind.TailwindError, match="Checksum mismatch"):
		tailwind.ensure_binary("4.9.9")

	assert list((home / "tailwind" / "4.9.9").iterdir()) == []


def test_a_cli_that_doesnt_run_isnt_kept(home, monkeypatch):

	serve_release(monkeypatch, f"#!{sys.executable}\nimport sys; sys.exit(3)\n".encode())

	with pytest.raises(tailwind.TailwindError, match="doesn't run"):
		tailwind.ensure_binary("4.9.9")

	assert list((home / "tailwind" / "4.9.9").iterdir()) == []


def test_an_unknown_version_says_so(monkeypatch):

	def missing(url, timeout=None):
		raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

	monkeypatch.setattr(tailwind.urllib.request, "urlopen", missing)

	with pytest.raises(tailwind.TailwindError, match="No Tailwind CSS 4.0.99 release.*tailwind.version"):
		tailwind.ensure_binary("4.0.99")


def test_offline_says_how_to_install_it_by_hand(home, monkeypatch):

	def offline(url, timeout=None):
		raise urllib.error.URLError("Name or service not known")

	monkeypatch.setattr(tailwind.urllib.request, "urlopen", offline)

	with pytest.raises(tailwind.TailwindError) as error:
		tailwind.ensure_binary()

	message = str(error.value)
	assert "Couldn't download Tailwind CSS" in message and "Name or service not known" in message
	assert tailwind.asset_name() in message
	assert f"{tailwind.RELEASES_URL}/tag/v{tailwind.DEFAULT_VERSION}" in message
	assert f"set {tailwind.ENV_BIN} to its path" in message
	assert str(home / "tailwind" / tailwind.DEFAULT_VERSION) in message


# Watching while debugging


def test_the_watcher_builds_then_rebuilds_as_files_change(tmp_path, fake_cli, stop_watchers):

	(tmp_path / "page.py").write_text('x = "tw-one"')
	options = tailwind.options({"tailwind": True}, tmp_path)

	watcher = tailwind.watch(tmp_path, options)

	# Built before it returns, so the first page has its CSS
	assert ".tw-one" in options["output"].read_text()
	assert "--watch" in watcher.process.args
	assert "--minify" not in watcher.process.args

	(tmp_path / "page.py").write_text('x = "tw-one tw-two"')
	wait_until(lambda: ".tw-two" in options["output"].read_text(), 10, "not rebuilt")

	process = watcher.process
	watcher.stop()
	assert process.poll() is not None


def test_a_watcher_that_cant_start_is_logged_not_raised(tmp_path, monkeypatch, capsys):

	def offline(url, timeout=None):
		raise urllib.error.URLError("no network")

	monkeypatch.setattr(tailwind.urllib.request, "urlopen", offline)

	assert tailwind.watch(tmp_path, tailwind.options({"tailwind": True}, tmp_path)) is None
	assert "Couldn't download Tailwind CSS" in capsys.readouterr().err


def test_app_run_in_debug_watches(tmp_path, fake_cli, monkeypatch, stop_watchers):

	import domino.asgi
	monkeypatch.setattr(domino.asgi, "serve", lambda *args, **kwargs: None)
	app = make_app(tmp_path / "app", {"tailwind": True, "mongo": {"auto": False}})

	app.run(debug=True)

	assert len(tailwind._watchers) == 1
	assert tailwind._watchers[0].process.poll() is None
	assert tailwind._watchers[0].root == tmp_path.resolve() / "app"


WATCHING_PROCESS = '''\
import sys, time
from domino import tailwind
tailwind.watch(sys.argv[1], tailwind.options({"tailwind": True}, sys.argv[1]))
print("watching", flush=True)
if sys.argv[2] == "exit":
	sys.exit(0)
time.sleep(60)
'''


def fake_pid(folder):

	path = Path(folder) / ".domino" / "tailwind.css.pid"
	wait_until(path.exists, 10, "the CLI didn't start watching")

	return int(path.read_text())


@pytest.mark.parametrize("how", ["exit", "SIGTERM", "SIGKILL"])
def test_the_watching_cli_never_outlives_the_server(tmp_path, fake_cli, how):

	if os.name == "nt" and how != "exit":
		pytest.skip("POSIX signals")

	env = dict(os.environ, PYTHONPATH=str(Path(__file__).parent.parent))
	server = subprocess.Popen([sys.executable, "-c", WATCHING_PROCESS, str(tmp_path), how], stdout=subprocess.PIPE, env=env)
	try:
		assert server.stdout.readline() == b"watching\n"
		pid = fake_pid(tmp_path)
		if how != "exit":
			assert running(pid)
			server.send_signal(getattr(signal, how))
		server.wait(10)

		wait_until(lambda: not running(pid), 10, f"the CLI (pid {pid}) outlived the server")
	finally:
		if server.poll() is None:
			server.kill()
			server.wait()
		server.stdout.close()


# The command line


def test_tailwind_build_command(tmp_path, fake_cli, capsys):

	make_app(tmp_path / "app", {"tailwind": True}, {"pages/index.py": 'x = "tw-deploy"'})

	assert cli.main(["tailwind", "build", str(tmp_path / "app")]) == 0

	output = tmp_path / "app" / ".domino" / "tailwind.css"
	assert output.read_text().startswith("/*minified*/")
	assert ".tw-deploy" in output.read_text()
	assert f"Tailwind CSS: built {output.resolve()}" in capsys.readouterr().err


def test_tailwind_build_needs_tailwind_on(tmp_path, capsys):

	make_app(tmp_path / "app", {}, {"app.py": ""})

	assert cli.main(["tailwind", "build", str(tmp_path / "app")]) == 1
	assert "doesn't use Tailwind CSS" in capsys.readouterr().err


def test_tailwind_build_reports_errors_in_one_line(tmp_path, monkeypatch, capsys):

	def offline(url, timeout=None):
		raise urllib.error.URLError("no network")

	monkeypatch.setattr(tailwind.urllib.request, "urlopen", offline)
	make_app(tmp_path / "app", {"tailwind": True}, {"app.py": ""})

	assert cli.main(["tailwind", "build", str(tmp_path / "app")]) == 1
	assert capsys.readouterr().err.startswith("domino: Couldn't download Tailwind CSS")


def test_tailwind_alone_prints_its_help(capsys):

	assert cli.main(["tailwind"]) == 2
	assert "build" in capsys.readouterr().out


def test_serve_builds_before_starting_the_workers(tmp_path, fake_cli, monkeypatch):

	import domino.workers
	monkeypatch.setattr(domino.workers, "serve", lambda *args: 0)
	make_app(tmp_path / "app", {"tailwind": True}, {"app.py": "", "pages/index.py": 'x = "tw-served"'})

	assert cli.main(["serve", str(tmp_path / "app"), "--workers", "2"]) == 0

	assert ".tw-served" in (tmp_path / "app" / ".domino" / "tailwind.css").read_text()


def test_create_with_tailwind(tmp_path, capsys):

	assert cli.main(["create", str(tmp_path / "site"), "--tailwind"]) == 0

	settings = json.loads((tmp_path / "site" / "settings.json").read_text())
	assert settings["tailwind"] is True
	assert 'class_="' in (tmp_path / "site" / "pages" / "layout.py").read_text()
	assert "dark:bg-slate-900" in (tmp_path / "site" / "components" / "tasks.py").read_text()


# The real CLI (opt-in: only if it's downloaded already, e.g. by running examples/tailwind)


# Read before the `home` fixture points DOMINO_HOME elsewhere
REAL_CLI = tailwind.binary_path(tailwind.DEFAULT_VERSION)


@pytest.mark.skipif(not REAL_CLI.is_file(), reason=f"Tailwind's CLI isn't downloaded ({REAL_CLI})")
def test_the_real_cli_builds_the_example(tmp_path, monkeypatch):

	monkeypatch.setenv(tailwind.ENV_BIN, str(REAL_CLI))
	app = tmp_path / "tailwind"
	shutil.copytree(EXAMPLES / "tailwind", app, ignore=shutil.ignore_patterns(".domino", "__pycache__"))
	(app / "components" / "extra.py").write_text(textwrap.dedent('''\
		# Class names inside any Python string are found
		classes = {"class": 'p-4 grid-cols-7'}
	'''))

	options = tailwind.options({"tailwind": True}, app)
	css = tailwind.build(app, options, minify=False).read_text()

	for utility in [".p-4", ".px-6", ".dark\\:bg-slate-900", ".md\\:flex", ".lg\\:grid-cols-3", ".grid-cols-7", ".data-loading\\:opacity-60",
			".hover\\:bg-indigo-500", ".bg-indigo-600"]:
		assert utility in css, utility
	# From the paired Jinja template
	assert ".shadow-indigo-600\\/20" in css
	# Dark mode follows the system setting
	assert "prefers-color-scheme: dark" in css

	minified = tailwind.build(app, options, minify=True).read_text()
	assert len(minified) < len(css) and "\n  " not in minified
