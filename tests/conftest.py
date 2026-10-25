import asyncio
import importlib.util
import os
import socket
import sys
import threading
import time
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


EXAMPLES = Path(__file__).parent.parent / "examples"


def forget(folder):
	"""Drop the modules imported from an app folder (its pages, components, data) and take
	the folder off the import path, so the next app's components/ and data.py are its own."""

	folder = os.path.abspath(folder)

	for name, module in list(sys.modules.items()):
		paths = [getattr(module, "__file__", None) or ""] + list(getattr(module, "__path__", None) or [])
		if any(os.path.abspath(path).startswith(folder + os.sep) for path in paths if path):
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
