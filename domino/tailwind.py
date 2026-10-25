"""Tailwind CSS with nothing to set up. Tailwind's standalone CLI (one executable, no Node) is
downloaded once into ~/.domino/tailwind/<version>/ (or $DOMINO_HOME/tailwind), like the
development MongoDB, and builds the CSS for the class names in the app's .py and .html files into
.domino/tailwind.css, which every page links. While debugging it rebuilds as files change and open
pages swap in the new CSS; in production it's built once, minified."""

import asyncio
import atexit
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from flask import Response, abort, current_app, has_app_context, request, send_file

from .devmongo import copy_with_progress, die_with_parent, domino_home, file_lock, log


DEFAULT_VERSION = "4.3.3"

RELEASES_URL = "https://github.com/tailwindlabs/tailwindcss/releases"

# A Tailwind CLI to use instead of downloading one
ENV_BIN = "DOMINO_TAILWIND_BIN"

# In the app's folder: the input CSS (@import "tailwindcss", a @theme...), and it turns Tailwind on
INPUT_NAME = "tailwind.css"

# In the app's folder: the CSS built, and the input made for apps without their own
OUTPUT = Path(".domino") / "tailwind.css"
GENERATED_INPUT = Path(".domino") / "tailwind.input.css"

URL = "/_domino/tailwind.css"
WATCH_URL = "/_domino/tailwind/watch"

# Seconds between looks at the built CSS, for pages waiting for it to change (debug only)
POLL = 0.25

CACHE_FOREVER = "public, max-age=31536000, immutable"

# Paths are relative to this file, in .domino/. Tailwind's own detection would also read .domino/
# (the development MongoDB's log, say) unless .gitignore lists it
GENERATED = '''\
/* Made by Domino. To customize Tailwind (a @theme, plugins...), put a tailwind.css in the app's
   folder instead, starting with @import "tailwindcss"; */
@import "tailwindcss" source(none);
@source "../**/*.{py,html}";
@source not "../.domino";
'''

ARCHES = {
	"x86_64": "x64",
	"amd64": "x64",
	"aarch64": "arm64",
	"arm64": "arm64",
}


class TailwindError(RuntimeError):
	"""Tailwind's CLI couldn't be downloaded, or the CSS couldn't be built."""


def options(settings, root):
	"""How the app at `root` uses Tailwind, or None if it doesn't: {"version", "input", "output"},
	`input` being None for the one Domino makes. It's on with the setting {"tailwind": true} (or
	{"tailwind": {"version": ..., "input": ...}}), or when the app's folder has a tailwind.css;
	{"tailwind": false} turns it off."""

	root = Path(root).resolve()
	setting = settings.get("tailwind")

	if setting is None:
		if not (root / INPUT_NAME).is_file():
			return None
		setting = {}
	elif not isinstance(setting, dict):
		if not setting:
			return None
		setting = {}

	input = None
	if setting.get("input"):
		input = root / setting["input"]
	elif (root / INPUT_NAME).is_file():
		input = root / INPUT_NAME

	return {
		"version": str(setting.get("version") or DEFAULT_VERSION).lstrip("v"),
		"input": input,
		"output": root / OUTPUT,
	}


# The CLI


def asset_name(system=None, machine=None, musl=None):
	"""The file name of Tailwind's standalone CLI for this OS and CPU in its GitHub releases."""

	if system is None:
		system = platform.system()

	if machine is None:
		machine = platform.machine()

	arch = ARCHES.get(machine.lower())

	if system == "Windows":
		# x64 builds only; Windows on ARM runs them
		return "tailwindcss-windows-x64.exe"

	if arch is not None and system == "Darwin":
		return f"tailwindcss-macos-{arch}"

	if arch is not None and system == "Linux":
		if musl is None:
			musl = any(Path("/lib").glob("ld-musl-*"))
		return f"tailwindcss-linux-{arch}" + ("-musl" if musl else "")

	raise TailwindError(f"Tailwind CSS has no standalone CLI for {system} on {machine}; install one and set {ENV_BIN} to its path")


def binary_path(version, environ=None):

	name = "tailwindcss.exe" if os.name == "nt" else "tailwindcss"

	return domino_home(environ) / "tailwind" / version / name


def find_binary(version=DEFAULT_VERSION, environ=None):
	"""The CLI to use without downloading anything: $DOMINO_TAILWIND_BIN or the cached download,
	or None."""

	if environ is None:
		environ = os.environ

	if environ.get(ENV_BIN):
		path = Path(environ[ENV_BIN]).expanduser()
		if not path.is_file():
			raise TailwindError(f"{ENV_BIN} is {path}, which isn't a file")
		return path

	path = binary_path(version, environ)

	return path if path.is_file() else None


def ensure_binary(version=DEFAULT_VERSION, environ=None):
	"""Path to Tailwind's CLI, downloading it the first time."""

	path = find_binary(version, environ)
	if path is not None:
		return path

	path = binary_path(version, environ)

	# Another `domino run` may be downloading the same version
	with file_lock(path.parent.parent / f"{version}.lock"):
		if not path.is_file():
			download(version, path)

	return path


def download(version, path):

	asset = asset_name()
	base = f"{RELEASES_URL}/download/v{version}/"
	url = base + asset

	try:
		expected = checksum(fetch(base + "sha256sums.txt").decode("utf-8", "replace"), asset)
		if expected is None:
			raise TailwindError(f"{base}sha256sums.txt has no checksum for {asset}")

		log(f"Downloading Tailwind CSS {version} ({asset}) from {url}")

		path.parent.mkdir(parents=True, exist_ok=True)
		handle, temp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".part")
		try:
			with os.fdopen(handle, "wb") as out, urllib.request.urlopen(url, timeout=60) as response:
				digest = copy_with_progress(response, out, int(response.headers.get("Content-Length") or 0), "sha256", "Tailwind CSS")

			if digest != expected:
				raise TailwindError(f"Checksum mismatch for {url}: expected {expected}, got {digest}")

			os.chmod(temp, 0o755)
			check_runs(temp)
			os.replace(temp, path)
		except BaseException:
			Path(temp).unlink(missing_ok=True)
			raise
	except urllib.error.HTTPError as error:
		if error.code == 404:
			raise TailwindError(f"No Tailwind CSS {version} release with {asset} at {RELEASES_URL} (HTTP 404); check the setting tailwind.version") from None
		raise TailwindError(offline(version, asset, path, f"HTTP {error.code}")) from None
	except (urllib.error.URLError, OSError) as error:
		raise TailwindError(offline(version, asset, path, getattr(error, "reason", None) or error)) from None


def offline(version, asset, path, reason):

	return (
		f"Couldn't download Tailwind CSS {version} ({reason}). Download {asset} from "
		f"{RELEASES_URL}/tag/v{version} yourself and set {ENV_BIN} to its path, or save it as {path}"
	)


def fetch(url):

	with urllib.request.urlopen(url, timeout=60) as response:
		return response.read()


def checksum(sums, asset):
	"""The SHA-256 of `asset` in a release's sha256sums.txt ("<hex>  ./<asset>" lines)."""

	for line in sums.splitlines():
		parts = line.split()
		if len(parts) == 2 and parts[1].lstrip("*").split("/")[-1] == asset:
			return parts[0].lower()

	return None


def check_runs(path):

	try:
		result = subprocess.run([str(path), "--help"], stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
	except (OSError, subprocess.TimeoutExpired) as error:
		raise TailwindError(f"The downloaded Tailwind CSS CLI doesn't run: {error}") from None

	if result.returncode != 0 or b"tailwindcss" not in result.stdout + result.stderr:
		raise TailwindError(f"The downloaded Tailwind CSS CLI doesn't run (exit code {result.returncode})")


# Building


def input_file(root, tailwind):
	"""The input CSS: the app's own, or the one Domino makes in .domino/."""

	if tailwind["input"] is not None:
		if not tailwind["input"].is_file():
			raise TailwindError(f"No Tailwind CSS input at {tailwind['input']} (the setting tailwind.input)")
		return tailwind["input"]

	path = Path(root).resolve() / GENERATED_INPUT
	path.parent.mkdir(parents=True, exist_ok=True)

	# Written only when it changes, so a watching CLI doesn't rebuild for nothing
	try:
		current = path.read_text(encoding="utf-8")
	except OSError:
		current = None
	if current != GENERATED:
		path.write_text(GENERATED, encoding="utf-8")

	return path


def command(binary, input, output, minify=False, watch=False):

	command = [str(binary), "--input", str(input), "--output", str(output)]

	if minify:
		command.append("--minify")

	if watch:
		# Without "=always" it stops when its stdin closes: when this process ends, however it ends
		command.extend(["--watch", "--silent"])

	return command


def build(root, tailwind, minify=True, download=True):
	"""Build the app's CSS into .domino/tailwind.css (minified for production) and return its path."""

	root = Path(root).resolve()
	binary = ensure_binary(tailwind["version"]) if download else find_binary(tailwind["version"])
	if binary is None:
		raise TailwindError(f"Tailwind CSS {tailwind['version']} isn't downloaded; run `domino tailwind build` or set {ENV_BIN}")

	output = tailwind["output"]
	output.parent.mkdir(parents=True, exist_ok=True)

	# Run in the app's folder: an input with a plain @import "tailwindcss" finds classes from there
	try:
		result = subprocess.run(command(binary, input_file(root, tailwind), output, minify), cwd=str(root),
			stdin=subprocess.DEVNULL, capture_output=True)
	except OSError as error:
		raise TailwindError(f"Couldn't run Tailwind CSS ({binary}): {error}") from None

	if result.returncode != 0:
		text = (result.stderr + result.stdout).decode("utf-8", "replace").strip()
		raise TailwindError(f"Tailwind CSS failed (exit code {result.returncode}):\n{text}")

	return output


def prepare(root, tailwind):
	"""For production (`domino serve`), before serving: build minified CSS with the CLI if it's
	already downloaded; else use a .domino/tailwind.css built beforehand (by `domino tailwind build`
	in a Dockerfile, say); else download the CLI and build. Logs what went wrong rather than raising,
	as the app works without its CSS."""

	if not tailwind:
		return None

	output = tailwind["output"]

	try:
		if find_binary(tailwind["version"]) is None and output.is_file():
			log(f"Tailwind CSS: {output}, built beforehand")
			return output
		build(root, tailwind, minify=True)
	except TailwindError as error:
		if output.is_file():
			log(f"Tailwind CSS: {error}\ndomino: Tailwind CSS: using {output}, built before")
			return output
		log(f"Tailwind CSS: {error}")
		return None

	log(f"Tailwind CSS: built {output}")

	return output


class Watcher:
	"""Tailwind's CLI rebuilding an app's CSS whenever its files change, while debugging."""


	def __init__(self, root, tailwind):

		self.root = Path(root).resolve()
		self.tailwind = tailwind
		self.process = None


	def start(self):

		binary = ensure_binary(self.tailwind["version"])

		# Once now, so the first page has its CSS (and a broken input shows at once)
		try:
			build(self.root, self.tailwind, minify=False)
		except TailwindError as error:
			log(f"Tailwind CSS: {error}")

		options = {}
		if os.name != "nt" and sys.platform.startswith("linux") and threading.current_thread() is threading.main_thread():
			# Also gone if this process is killed, even before its stdin closes
			options["preexec_fn"] = die_with_parent

		# Its stdin is a pipe only this process holds: when it ends, the CLI does too
		try:
			self.process = subprocess.Popen(
				command(binary, input_file(self.root, self.tailwind), self.tailwind["output"], watch=True),
				cwd=str(self.root), stdin=subprocess.PIPE, **options
			)
		except OSError as error:
			raise TailwindError(f"Couldn't run Tailwind CSS ({binary}): {error}") from None
		stop_on_exit(self)

		return self


	def stop(self, timeout=5):

		process = self.process
		if process is None:
			return
		self.process = None

		if process.poll() is None:
			try:
				process.stdin.close()
				process.wait(timeout)
			except (OSError, subprocess.TimeoutExpired):
				process.kill()
				process.wait()
		elif process.stdin:
			process.stdin.close()


_watchers = []


def stop_all():

	while _watchers:
		_watchers.pop().stop()


def stop_on_exit(watcher):

	if not _watchers:
		atexit.register(stop_all)

	_watchers.append(watcher)


def watch(root, tailwind):
	"""Start rebuilding the app's CSS as its files change, until this process ends. Logs what went
	wrong rather than raising, as the app works without its CSS."""

	try:
		watcher = Watcher(root, tailwind).start()
	except TailwindError as error:
		log(f"Tailwind CSS: {error}")
		return None

	log(f"Tailwind CSS: {tailwind['output']}, rebuilt as files change")

	return watcher


# Serving


_versions = {}  # path -> ((mtime, size), version)


def version(path):
	"""A short hash of the built CSS, for its URL, or None if it isn't built."""

	try:
		stat = os.stat(path)
		key = (stat.st_mtime_ns, stat.st_size)
		cached = _versions.get(path)
		if cached is not None and cached[0] == key:
			return cached[1]
		digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]
	except OSError:
		return None

	_versions[path] = (key, digest)

	return digest


def link(level=0, indent=""):
	"""The <link> to the app's Tailwind CSS for a page's <head>, or "" when Tailwind is off."""

	if not has_app_context():
		return ""

	tailwind = getattr(current_app, "tailwind", None)
	if not tailwind:
		return ""

	current = version(tailwind["output"])
	href = URL + (f"?v={current}" if current else "")

	# core.js listens for rebuilds while debugging
	watching = " data-domino-watch" if current_app.debug else ""
	end = "" if indent == "" else "\n"

	return f'{indent * level}<link rel="stylesheet" href="{href}" data-domino-tailwind{watching}>{end}'


def add_routes(app):

	tailwind = app.tailwind
	output = tailwind["output"]
	lock = threading.Lock()
	tried = []

	def stylesheet():

		# Served by something that didn't build it (`flask run`, `uvicorn app:app.asgi`): once
		if not output.is_file() and not tried:
			with lock:
				if not tried:
					tried.append(True)
					try:
						build(app.root_path, tailwind, minify=not app.debug, download=app.debug)
					except TailwindError as error:
						log(f"Tailwind CSS: {error}")

		current = version(output)
		if current is None:
			return Response(f"/* Tailwind CSS isn't built: run `domino tailwind build` */\n", 404, mimetype="text/css")

		response = send_file(output, mimetype="text/css", conditional=True)
		# The URL names the content, so the browser can keep it; a rebuild has a new one
		response.headers["Cache-Control"] = CACHE_FOREVER if request.args.get("v") == current else "no-cache"

		return response

	def watch():

		if not app.debug:
			abort(404)

		keepalive = app.config["DOMINO_KEEPALIVE"]

		def events():

			yield "retry: 500\n\n"
			last = None
			quiet = 0
			while True:
				current = version(output)
				if current and current != last:
					last = current
					quiet = 0
					yield f"data: {json.dumps({'version': current})}\n\n"
				elif quiet >= keepalive:
					quiet = 0
					yield ": keepalive\n\n"
				time.sleep(POLL)
				quiet += POLL

		return Response(events(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

	app.add_url_rule(URL, URL, stylesheet, methods=["GET"])
	app.add_url_rule(WATCH_URL, WATCH_URL, watch, methods=["GET"])


async def changes(output, disconnected, keepalive):
	"""The built CSS's version, at first and each time it changes, or None after `keepalive`
	seconds without one, until `disconnected` is done."""

	last = None
	quiet = 0

	while not disconnected.done():
		current = version(output)
		if current and current != last:
			last = current
			quiet = 0
			yield current
		elif quiet >= keepalive:
			quiet = 0
			yield None
		await asyncio.wait([disconnected], timeout=POLL)
		quiet += POLL


async def serve_watch(app, scope, receive, send):
	"""WATCH_URL over ASGI, without holding a thread: tells the page what the CSS's version is
	when it connects (again after a restart: it may have changed meanwhile) and each time it
	changes. Over a WebSocket, which the server closes at once when it stops or restarts on a
	change, unlike a Server-Sent Events stream, which it would wait for (the pages it serves
	without the socket use one)."""

	from .asgi import wait_for_disconnect

	output = app.tailwind["output"]
	keepalive = app.config["DOMINO_KEEPALIVE"]

	if scope["type"] == "websocket":
		if (await receive())["type"] != "websocket.connect":
			return
		await send({"type": "websocket.accept"})
		disconnected = asyncio.ensure_future(wait_for_close(receive))
	else:
		await send({"type": "http.response.start", "status": 200, "headers": [
			(b"content-type", b"text/event-stream; charset=utf-8"),
			(b"cache-control", b"no-cache"),
			(b"x-accel-buffering", b"no"),
		]})
		await send({"type": "http.response.body", "body": b"retry: 500\n\n", "more_body": True})
		disconnected = asyncio.ensure_future(wait_for_disconnect(receive))

	try:
		async for current in changes(output, disconnected, keepalive):
			if scope["type"] == "websocket":
				if current:
					await send({"type": "websocket.send", "text": json.dumps({"version": current})})
			elif current:
				await send({"type": "http.response.body", "body": f"data: {json.dumps({'version': current})}\n\n".encode(), "more_body": True})
			else:
				await send({"type": "http.response.body", "body": b": keepalive\n\n", "more_body": True})
	except (asyncio.CancelledError, OSError, RuntimeError):
		# The client went away, or the server is stopping and won't wait for this
		pass
	finally:
		disconnected.cancel()


async def wait_for_close(receive):

	while (await receive())["type"] != "websocket.disconnect":
		pass
