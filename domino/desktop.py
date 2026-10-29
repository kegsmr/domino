"""Desktop apps: a Domino app in a native window, with pywebview.

`domino desktop [app]` runs the app as `domino run` does (hot reload, the development MongoDB) and
shows it in a window instead of a browser tab. `domino build --desktop [app]` packages it with
PyInstaller into one program that serves the app inside itself and shows it in a window.

The server listens on 127.0.0.1 only, and answers only the window: each launch makes a random
token, which the window's first URL carries once and then keeps in a cookie. Requests and
sockets without it are refused, so other programs and web pages on the machine can't use the app.
"""

import _thread
import ast
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# The launch's token, for the server (also in the reloader's process, through the environment)
ENV_TOKEN = "DOMINO_DESKTOP_TOKEN"

# The window's process, which `domino run` watches, to stop if it ends without stopping it
ENV_PARENT = "DOMINO_DESKTOP_PARENT"

# The cookie that holds it, and the query parameter that brings it the first time
COOKIE = "domino_desktop"

# For CI: the packaged program loads its page and prints the result instead of opening a window
ENV_SMOKE = "DOMINO_DESKTOP_SMOKE"

# Folders of the app that aren't packaged
SKIPPED_FOLDERS = {".git", ".domino", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache", "build", "dist"}

INSTALL_HINT = "pip install pywebview pyinstaller (or pip install domino-web[desktop])"

LAUNCHER = '''\
# Written by `domino build --desktop`: the packaged program's entry point
import os
import sys

from domino.desktop import launch

sys.exit(launch(os.path.join(sys._MEIPASS, "app"), {name!r}))
'''


class DesktopError(Exception):
	"""A problem worth one line on stderr, not a traceback."""


# The token check, in the server


def token():
	"""This launch's token, or None when the app isn't running as a desktop app."""

	return os.environ.get(ENV_TOKEN) or None


def cookies(scope):

	from http.cookies import SimpleCookie

	header = b"; ".join(value for name, value in scope.get("headers") or [] if name == b"cookie")
	jar = SimpleCookie()
	try:
		jar.load(header.decode("latin-1"))
	except Exception:
		return {}

	return {name: morsel.value for name, morsel in jar.items()}


async def admit(expected, scope, receive, send):
	"""Whether a request or socket may reach the app: it has the token's cookie. A page load with
	?domino_desktop=<token> gets the cookie and is sent on to the same URL without it. Anything
	else is refused here. Returns False when it answered."""

	if scope["type"] == "lifespan":
		return True

	if secrets.compare_digest(cookies(scope).get(COOKIE, ""), expected):
		return True

	query = urllib.parse.parse_qs(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
	given = (query.pop(COOKIE, None) or [""])[0]

	if scope["type"] == "http" and secrets.compare_digest(given, expected):
		rest = urllib.parse.urlencode(query, doseq=True)
		location = scope.get("path", "/") + (f"?{rest}" if rest else "")
		await send({"type": "http.response.start", "status": 303, "headers": [
			(b"location", location.encode("latin-1")),
			(b"set-cookie", f"{COOKIE}={expected}; Path=/; HttpOnly; SameSite=Strict".encode("latin-1")),
			(b"cache-control", b"no-store"),
		]})
		await send({"type": "http.response.body", "body": b""})
		return False

	if scope["type"] == "websocket":
		# Refused during the handshake
		await receive()
		await send({"type": "websocket.close", "code": 1008})
		return False

	await send({"type": "http.response.start", "status": 403, "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
	await send({"type": "http.response.body", "body": b"This app only answers its own window."})
	return False


# The window


def free_port():

	with socket.socket() as sock:
		sock.bind(("127.0.0.1", 0))
		return sock.getsockname()[1]


def wait_for(port, alive=lambda: True, timeout=120):
	"""Wait until something listens on the port. False if `alive()` turns false first, or on timeout."""

	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		if not alive():
			return False
		try:
			with socket.create_connection(("127.0.0.1", port), timeout=1):
				return True
		except OSError:
			time.sleep(0.1)

	return False


def options(folder, name=None):
	"""The main window's options: <window main title="Notes" width="1200" height="800"> in one of the
	app's templates, the rest by default. The title defaults to the app's folder's name (`name`, for
	a packaged app, whose folder is "app")."""

	found = {
		"title": (name or Path(folder).name).replace("-", " ").replace("_", " ").title(),
		"width": 1024,
		"height": 768,
	}
	found.update(main_window(folder))

	return found


def main_window(folder):
	"""The options of <window main ...>, read from the app's templates without importing the app."""

	from . import dtemplates
	from .templates import DEFINITION_START

	for root, folders, files in os.walk(folder):
		folders[:] = sorted(name for name in folders if name not in SKIPPED_FOLDERS and not name.startswith("."))
		for name in sorted(files):
			if not name.endswith(".html"):
				continue
			path = os.path.join(root, name)
			try:
				with open(path, encoding="utf-8") as file:
					source = file.read()
			except (OSError, UnicodeDecodeError):
				continue
			if "<window" in source and DEFINITION_START.match(source):
				compiled = dtemplates.parse_file(path, source)
				if compiled.main_window is not None:
					return compiled.main_window

	return {}


def import_webview():

	try:
		import webview
	except ImportError:
		raise DesktopError(f"Desktop apps need pywebview: {INSTALL_HINT}") from None

	return webview


def show(port, value, settings, state):
	"""Open the main window, at the app's first page, and wait until it's closed. `state` is the
	file where windows' sizes and places are remembered."""

	webview = import_webview()
	windows = Windows(f"http://127.0.0.1:{port}", value, state)
	windows.create("main", "/", settings)
	webview.start()


class Windows:
	"""The app's windows in this process: the main one, and those its pages open (see
	domino.windows). Each is opened once at a time, and remembers its size and place."""


	def __init__(self, base, value, state=None):

		self.base = base
		self.value = value  # the launch's token, which each window's first URL carries
		self.state = Path(state) if state else None
		self.open = {}  # name -> pywebview window
		self.urls = {}  # name -> what it shows (/_domino/window/Settings?values=...)
		self.saved = {}
		if self.state is not None:
			try:
				self.saved = json.loads(self.state.read_text(encoding="utf-8"))
			except (OSError, ValueError):
				self.saved = {}


	def create(self, name, url, options):

		webview = import_webview()

		remember = options.get("remember", True) and self.state is not None
		place = (self.saved.get(name) or {}) if remember else {}
		size = {
			"width": place.get("width") or options.get("width") or 640,
			"height": place.get("height") or options.get("height") or 480,
		}
		# The place too, but on Linux, where what X11 window managers report and what they're
		# asked for differ by the title bar, so a window would creep down at each launch
		if "x" in place and "y" in place and sys.platform in ("win32", "darwin"):
			size.update(x=place["x"], y=place["y"])
		if "min-width" in options or "min-height" in options:
			size["min_size"] = (options.get("min-width", 200), options.get("min-height", 100))

		window = webview.create_window(
			options.get("title") or name, self.address(url),
			js_api=Bridge(self, name), resizable=options.get("resizable", True), on_top=options.get("on-top", False),
			maximized=options.get("maximized", False), **size,
		)
		self.open[name] = window
		self.urls[name] = url

		def closing():
			if remember:
				self.remember(name, window)

		def closed():
			self.open.pop(name, None)
			# Closing the main window ends the program, with its other windows
			if name == "main":
				for other in list(self.open.values()):
					other.destroy()

		window.events.closing += closing
		window.events.closed += closed

		return window


	def address(self, url):
		"""The URL a window loads: the app's, with the token for its first request."""

		separator = "&" if "?" in url else "?"

		return f"{self.base}{url}{separator}{COOKIE}={self.value}"


	def remember(self, name, window):

		try:
			self.saved[name] = {"width": window.width, "height": window.height, "x": window.x, "y": window.y}
			self.state.parent.mkdir(parents=True, exist_ok=True)
			self.state.write_text(json.dumps(self.saved, indent=1), encoding="utf-8")
		except Exception:
			pass  # a size not remembered is no reason to stop closing


	def opened(self, spec):
		"""A page asked for a window (core.js, through Bridge.open_window)."""

		name = str(spec.get("name") or "")
		url = str(spec.get("url") or "")
		if not name.isidentifier() or not url.startswith(f"/_domino/window/{name}"):
			return

		# Open already: shown again, with the values it's opened with now (Settings.open(tab="audio"))
		window = self.open.get(name)
		if window is not None:
			if self.urls.get(name) != url:
				self.urls[name] = url
				window.load_url(self.address(url))
			window.restore()
			window.show()
			return

		self.create(name, url, spec)


class Bridge:
	"""What a window's page can call (window.pywebview.api in core.js). Names starting with _ are
	pywebview's to leave alone."""


	def __init__(self, windows, name):

		self._windows = windows
		self._name = name


	def open_window(self, spec):

		if isinstance(spec, dict):
			self._windows.opened(spec)


	def close_window(self):

		window = self._windows.open.get(self._name)
		if window is not None:
			window.destroy()


def state_file(folder=None, name=None):
	"""Where windows' sizes and places are kept: the app's .domino folder while developing, the
	user's settings folder for a packaged app (%APPDATA%, ~/Library/Application Support, ~/.config)."""

	if folder is not None:
		return Path(folder) / ".domino" / "windows.json"

	if os.name == "nt":
		base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
	elif sys.platform == "darwin":
		base = Path.home() / "Library" / "Application Support"
	else:
		base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")

	return base / name / "windows.json"


def first_url(port, value):

	return f"http://127.0.0.1:{port}/?{COOKIE}={value}"


def app_folder(path):

	path = Path(path).resolve()
	if path.is_file():
		return path.parent
	if not (path / "app.py").is_file() and not (path / "pages").is_dir():
		raise DesktopError(f"No app.py or pages/ folder in {path}")

	return path


# domino desktop: the development server in a window


def run(path, port=None):
	"""`domino desktop`: `domino run` in a process of its own, shown in a window. Closing the
	window stops it."""

	folder = app_folder(path)
	webview = import_webview()  # noqa: F841 (checked before starting anything)

	value = secrets.token_urlsafe(32)
	port = port or free_port()

	command = [sys.executable, "-m", "domino", "run", str(path), "--port", str(port)]
	env = dict(os.environ, **{ENV_TOKEN: value, ENV_PARENT: str(os.getpid())})
	# Its own process group, so stopping it reaches the reloader and MongoDB as Ctrl+C would
	if os.name == "nt":
		server = subprocess.Popen(command, env=env, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
	else:
		server = subprocess.Popen(command, env=env, start_new_session=True)

	try:
		if not wait_for(port, alive=lambda: server.poll() is None):
			raise DesktopError("The app's server stopped before it started serving; see above")
		show(port, value, options(folder), state_file(folder))
	finally:
		stop(server)

	return 0


def watch_parent():
	"""In the `domino run` that `domino desktop` started: stop as Ctrl+C would if the window's
	process ends without stopping it (it crashed, or was killed), so no server is left behind."""

	# Taken out, so the reloader's processes don't watch too
	parent = os.environ.pop(ENV_PARENT, None)
	if not parent:
		return

	def watch():
		while alive(int(parent)):
			time.sleep(1)
		if os.name == "nt":
			_thread.interrupt_main()
		else:
			os.kill(os.getpid(), signal.SIGINT)

	threading.Thread(target=watch, daemon=True, name="domino-desktop-parent").start()


def alive(pid):
	"""Whether the process that started this one is still running."""

	if os.name != "nt":
		# A process whose parent ended is handed to another
		return os.getppid() == pid

	import ctypes

	kernel32 = ctypes.windll.kernel32
	handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
	if not handle:
		return False
	try:
		return kernel32.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT: still running
	finally:
		kernel32.CloseHandle(handle)


def stop(process, timeout=15):
	"""Stop `domino run` like Ctrl+C does, so its MongoDB stops too; kill it if it doesn't."""

	if process.poll() is not None:
		return

	try:
		if os.name == "nt":
			process.send_signal(signal.CTRL_BREAK_EVENT)
		else:
			os.killpg(process.pid, signal.SIGINT)
		process.wait(timeout)
	except (subprocess.TimeoutExpired, OSError):
		process.kill()
		process.wait()


# The packaged program


def launch(folder, name=None):
	"""The packaged program: serve the app in a thread of this process, on a free local port, and
	show it in a window. Closing the window ends the program."""

	import uvicorn

	from .cli import load_app
	from . import tailwind

	value = secrets.token_urlsafe(32)
	os.environ[ENV_TOKEN] = value

	app = load_app(folder)
	# Sessions last as long as the program runs, unless the app has a key of its own
	if not app.secret_key:
		app.secret_key = secrets.token_hex(32)
	tailwind.prepare(app.root_path, app.tailwind)

	port = free_port()
	server = uvicorn.Server(uvicorn.Config(app.asgi, host="127.0.0.1", port=port, log_level="warning", ws_per_message_deflate=False))
	thread = threading.Thread(target=server.run, daemon=True)
	thread.start()

	try:
		if not wait_for(port, alive=thread.is_alive):
			print("domino: the app's server didn't start", file=sys.stderr)
			return 1

		if os.environ.get(ENV_SMOKE):
			return smoke(port, value)

		from .deploy import slug
		settings = options(folder, name)
		show(port, value, settings, state_file(name=slug(settings["title"])))
	finally:
		server.should_exit = True
		thread.join(5)

	return 0


def smoke(port, value):
	"""Load the page as the window would, and without the token, and say how both went."""

	opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
	with opener.open(first_url(port, value), timeout=30) as response:
		page = response.read().decode("utf-8", errors="replace")
		print(f"domino: desktop smoke test: {response.status}, {len(page)} bytes, domino page: {'data-domino-page' in page}")

	try:
		urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=30)
		refused = False
	except urllib.error.HTTPError as error:
		refused = error.code == 403
	print(f"domino: desktop smoke test: without the token: {'refused' if refused else 'SERVED'}")

	return 0 if "data-domino-page" in page and refused else 1


# domino build --desktop


def imported_modules(folder):
	"""The top-level modules the app's Python files import, but its own: PyInstaller can't see
	them, since the app's files are loaded at run time."""

	local = {path.stem for path in folder.iterdir() if path.suffix == ".py"}
	local |= {path.name for path in folder.iterdir() if path.is_dir()}

	found = set()
	for path in python_files(folder):
		try:
			tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
		except SyntaxError:
			continue
		for node in ast.walk(tree):
			if isinstance(node, ast.Import):
				found.update(alias.name.split(".")[0] for alias in node.names)
			elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
				found.add(node.module.split(".")[0])

	return sorted(found - local - {"domino"})


def python_files(folder):

	for root, folders, files in os.walk(folder):
		folders[:] = [name for name in folders if name not in SKIPPED_FOLDERS and not name.startswith(".")]
		for name in files:
			if name.endswith(".py") and not name.endswith("_test.py"):
				yield Path(root) / name


def copy_app(folder, target):
	"""The app's files to package: not its tests, caches or virtualenvs, but its built Tailwind CSS."""

	def ignore(directory, names):
		skipped = {name for name in names if name in SKIPPED_FOLDERS or name.startswith(".")}
		skipped |= {name for name in names if name.endswith("_test.py")}
		return skipped

	if target.exists():
		shutil.rmtree(target)
	shutil.copytree(folder, target, ignore=ignore)

	css = folder / ".domino" / "tailwind.css"
	if css.is_file():
		(target / ".domino").mkdir()
		shutil.copy(css, target / ".domino" / "tailwind.css")


def build(path):
	"""Package the app with PyInstaller: dist/<name>.exe on Windows, dist/<name>.app on macOS and
	dist/<name> on Linux, in the app's folder. Returns the program's path."""

	from .deploy import slug, tailwind_step, uses_collections

	folder = app_folder(path)

	try:
		import PyInstaller  # noqa: F401
		import webview  # noqa: F401
	except ImportError:
		raise DesktopError(f"Packaging needs PyInstaller and pywebview: {INSTALL_HINT}") from None

	name = slug(options(folder)["title"])
	work = folder / ".domino" / "desktop"
	work.mkdir(parents=True, exist_ok=True)

	if tailwind_step(folder):
		subprocess.run([sys.executable, "-m", "domino", "tailwind", "build", str(folder)], check=True)

	if uses_collections(folder):
		print("domino: warning: the app uses named Collections, which need a MongoDB: the packaged app "
			"uses the mongo.url setting (Collection() without a name keeps its data in memory)", file=sys.stderr)

	copy_app(folder, work / "app")
	launcher = work / "launcher.py"
	launcher.write_text(LAUNCHER.format(name=folder.name), encoding="utf-8")

	command = [
		sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
		"--onefile", "--windowed", "--name", name,
		"--distpath", str(folder / "dist"), "--workpath", str(work / "build"), "--specpath", str(work),
		"--add-data", f"{work / 'app'}{os.pathsep}app",
		"--collect-all", "domino", "--collect-submodules", "uvicorn",
	]
	for module in imported_modules(folder):
		command += ["--hidden-import", module]
	command.append(str(launcher))

	print(f"domino: packaging {folder} with PyInstaller", file=sys.stderr, flush=True)
	if subprocess.run(command).returncode != 0:
		raise DesktopError("PyInstaller failed; see above")

	program = folder / "dist" / (f"{name}.exe" if os.name == "nt" else f"{name}.app" if sys.platform == "darwin" else name)
	size = sum(path.stat().st_size for path in program.rglob("*") if path.is_file()) if program.is_dir() else program.stat().st_size
	print(f"domino: built {program} ({size / 1_000_000:.0f} MB)", file=sys.stderr)

	return program
