import asyncio
import importlib.util
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest


# A MongoDB replica set for tests that need one, e.g. mongodb://127.0.0.1:27017/?replicaSet=rs0
MONGO_URL = os.environ.get("DOMINO_TEST_MONGO_URL")
DATABASE = f"domino_test_{uuid.uuid4().hex[:8]}"


def with_database(url, name):

	parts = urlsplit(url)

	return urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, parts.fragment))


def pytest_configure(config):

	config.addinivalue_line("markers", "mongo: needs MongoDB (set DOMINO_TEST_MONGO_URL)")

	# Each test run gets its own database, dropped at the end
	if MONGO_URL:
		os.environ["DOMINO_MONGO__URL"] = with_database(MONGO_URL, DATABASE)


def pytest_collection_modifyitems(config, items):

	if MONGO_URL:
		return

	skip = pytest.mark.skip(reason="needs MongoDB: set DOMINO_TEST_MONGO_URL")
	for item in items:
		if "mongo" in item.keywords:
			item.add_marker(skip)


def pytest_sessionfinish(session):

	if not MONGO_URL:
		return

	import pymongo

	with pymongo.MongoClient(MONGO_URL) as client:
		client.drop_database(DATABASE)


ROOT = Path(__file__).parent.parent
EXAMPLES = ROOT / "examples"


def forget(folder):
	"""Drop the modules imported from an app folder (its pages, components, data) and take
	the folder off the import path, so the next app's components/ and data.py are its own."""

	folder = os.path.abspath(folder)
	# Its own top-level modules (data, components, ...), whichever app's copy is loaded now
	own = {os.path.splitext(name)[0] for name in os.listdir(folder) if name.endswith(".py") or os.path.isdir(os.path.join(folder, name))}

	for name, module in list(sys.modules.items()):
		paths = [getattr(module, "__file__", None) or ""] + list(getattr(module, "__path__", None) or [])
		mine = any(os.path.abspath(path).startswith(folder + os.sep) for path in paths if path)
		# Another example's data.py or components/ would shadow this one's
		shadow = name.split(".")[0] in own and "examples" in os.path.abspath(paths[0] or "").split(os.sep)
		if mine or shadow:
			del sys.modules[name]

	sys.path[:] = [path for path in sys.path if os.path.abspath(path) != folder]


@pytest.fixture
def forget_modules():

	return forget


@pytest.fixture
def load_example():
	"""Imports examples/<name>/app.py like `python examples/<name>/app.py` would."""

	loaded = []

	def load(name):

		folder = EXAMPLES / name
		forget(folder)
		loaded.append(folder)

		# Like `python app.py`: the app's folder comes first on the import path
		sys.path.insert(0, str(folder))

		spec = importlib.util.spec_from_file_location(f"example_{name}", folder / "app.py")
		module = importlib.util.module_from_spec(spec)
		# Flask finds the app's folder (for settings.json and pages/) through sys.modules
		sys.modules[spec.name] = module
		spec.loader.exec_module(module)

		return module

	yield load

	for folder in loaded:
		forget(folder)


class ASGIServer:
	"""An app served by uvicorn in a thread, as `uvicorn myapp:app.asgi` would serve it."""


	def __init__(self, app):

		import uvicorn

		# Bound here, so the port is known before the server starts
		self.socket = socket.socket()
		self.socket.bind(("127.0.0.1", 0))
		self.port = self.socket.getsockname()[1]
		self.url = f"http://127.0.0.1:{self.port}/"
		self.ws_url = f"ws://127.0.0.1:{self.port}/_domino/ws"

		config = uvicorn.Config(app.asgi, loop="asyncio", log_level="warning", lifespan="off", timeout_graceful_shutdown=2)
		self.server = uvicorn.Server(config)
		self.loop = asyncio.new_event_loop()
		self.thread = threading.Thread(target=self.run, daemon=True)
		self.thread.start()

		deadline = time.monotonic() + 5
		while not self.server.started:
			assert time.monotonic() < deadline, "uvicorn didn't start"
			time.sleep(0.01)


	def run(self):

		asyncio.set_event_loop(self.loop)
		self.loop.run_until_complete(self.server.serve(sockets=[self.socket]))


	def stop(self):

		self.server.should_exit = True
		self.thread.join(5)
		self.socket.close()


@pytest.fixture
def asgi_server():
	"""Serves apps with uvicorn: asgi_server(app) returns an ASGIServer, stopped after the test."""

	servers = []

	def start(app):
		server = ASGIServer(app)
		servers.append(server)
		return server

	yield start

	for server in servers:
		server.stop()


def running(pid):

	try:
		with open(f"/proc/{pid}/stat") as stat:
			# A zombie has exited; it's only waiting to be reaped
			return stat.read().rsplit(")", 1)[1].split()[0] != "Z"
	except FileNotFoundError:
		return False
	except OSError:
		pass

	try:
		os.kill(pid, 0)
	except ProcessLookupError:
		return False

	return True


def wait_until(condition, timeout=10, message="timed out"):

	deadline = time.monotonic() + timeout
	while not condition():
		assert time.monotonic() < deadline, message
		time.sleep(0.05)


class Served:
	"""`domino serve <app> --workers N --port 0` in a subprocess."""


	def __init__(self, app, count=2, log_path=None):

		self.log_path = log_path or Path(app) / "serve.log"
		self.log = open(self.log_path, "w")

		env = dict(os.environ, PYTHONPATH=str(ROOT))
		env.pop("DOMINO_WORKER_ID", None)
		command = "import sys; from domino.cli import main; sys.exit(main(sys.argv[1:]))"
		self.process = subprocess.Popen([sys.executable, "-c", command, "serve", str(app), "--workers", str(count), "--port", "0"],
			stdout=self.log, stderr=subprocess.STDOUT, env=env, cwd=str(self.log_path.parent))
		self.pids = {}
		self.port = None


	def start(self):

		def started():
			match = re.search(r"App: http://127\.0\.0\.1:(\d+)/", self.output())
			if self.process.poll() is not None:
				raise AssertionError(f"domino serve exited:\n{self.output()}")
			if match:
				self.port = int(match.group(1))
			return match

		wait_until(started, 60, "domino serve didn't start")
		self.url = f"http://127.0.0.1:{self.port}/"
		self.ws_url = f"ws://127.0.0.1:{self.port}/_domino/ws"

		return self


	def output(self):

		return self.log_path.read_text()


	def get(self, path, headers=None):

		request = urllib.request.Request(self.url + path.lstrip("/"), headers=headers or {})
		with urllib.request.urlopen(request, timeout=10) as response:
			return response.read().decode()


	def workers(self, count=2):
		"""Worker id -> pid, asking until every worker has answered."""

		pids = {}
		while len(pids) < count:
			worker, pid = self.get("/worker").split()
			pids[int(worker)] = int(pid)
		self.pids.update(pids)

		return pids


	def stop(self):

		if self.process.poll() is None:
			self.process.terminate()
			try:
				self.process.wait(15)
			except subprocess.TimeoutExpired:
				self.process.kill()
				self.process.wait()

		# Never leave a worker behind, whatever the test did
		for pid in self.pids.values():
			if running(pid):
				os.kill(pid, signal.SIGKILL)
		self.log.close()
