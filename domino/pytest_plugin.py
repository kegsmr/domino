"""Tests that live next to their page: pages/about_test.py tests pages/about.py.

	# pages/index_test.py
	def test_increment(page):
		page.click("button", text="Increment")
		assert page.text("p") == "Current Count: 1"

`page` is the page this file tests, already open in a simulated browser (domino.testing),
and `open_page(**params)` opens it with URL parameters (pages/users/[id]_test.py) or opens
any path of the app. Installed with Domino, so plain `pytest` finds these files.

Like `meteor test`, these tests get MongoDB for named Collections without any setup: each test
uses a database of its own, dropped after it, on DOMINO_TEST_MONGO_URL, the app's mongo.url, or
else a mongod started (once, the first time a test connects) in a temporary folder and stopped
at the end of the session. `domino_db` gives the same to tests that use collections directly.

Emails are never sent in tests (domino.mail keeps them in memory); `mail_outbox` lists the ones
sent during the test.
"""

import importlib.util
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import pytest


TEST_SUFFIX = "_test.py"

# An existing MongoDB for tests (e.g. in CI); nothing is started then
ENV_TEST_URL = "DOMINO_TEST_MONGO_URL"

_apps = {}  # app folder -> its Domino app, loaded once per test session
_active = [None]  # the app folder whose modules (components, data, ...) are importable now


def page_test_target(path):
	"""(app folder, pages folder, page file) for a test file in a pages/ folder, else None."""

	path = Path(path)
	if not path.name.endswith(TEST_SUFFIX):
		return None

	for parent in path.parents:
		if parent.name == "pages":
			page = path.with_name(path.name[:-len(TEST_SUFFIX)] + ".py")
			return parent.parent, parent, page

	return None


def activate(folder):
	"""Make `folder`'s own modules importable, forgetting another app's same-named ones
	(two apps can both have components/ and data.py)."""

	folder = str(folder)
	previous = _active[0]
	if previous == folder:
		return

	if previous is not None:
		for name, module in list(sys.modules.items()):
			file = getattr(module, "__file__", None) or ""
			if file.startswith(previous + os.sep) and not name.startswith(("domino_page_tests.", "domino_app_", "domino_pages.")):
				del sys.modules[name]

	if folder in sys.path:
		sys.path.remove(folder)
	sys.path.insert(0, folder)
	_active[0] = folder


def load_app(folder):

	folder = Path(folder).resolve()
	activate(folder)

	app = _apps.get(folder)
	if app is None:
		from .cli import load_app as load

		app = _apps[folder] = load(folder)
		# Handler errors come back to the test with their traceback
		app.testing = True
		# Session cookies (accounts) need one; `domino run` makes one up the same way
		if not app.secret_key:
			app.secret_key = secrets.token_hex(16)

	return app


def import_test_file(path, name):

	# Through sys.meta_path, so pytest's assertion rewriting still applies
	for finder in sys.meta_path:
		find_spec = getattr(finder, "find_spec", None)
		spec = find_spec and find_spec(name, [str(path.parent)])
		if spec is not None:
			break
	else:
		raise ImportError(f"Can't import {path}")

	module = importlib.util.module_from_spec(spec)
	sys.modules[name] = module
	spec.loader.exec_module(module)

	return module


class PageTestModule(pytest.Module):
	"""A test file in pages/, imported under a name of its own: pages/index_test.py and
	pages/blog/index_test.py would otherwise clash, both being "index_test"."""


	def _getobj(self):

		folder, _, _ = page_test_target(self.path)
		activate(folder.resolve())

		unique = re.sub(r"\W", "_", str(self.path.parent.resolve()))
		return import_test_file(self.path, f"domino_page_tests.{unique}.{self.path.stem}")


def pytest_pycollect_makemodule(module_path, parent):

	if page_test_target(module_path) is not None:
		return PageTestModule.from_parent(parent, path=Path(module_path))

	return None


def pytest_addoption(parser):

	parser.addoption("--no-mongo", action="store_true", help=f"Domino: don't start a MongoDB for tests (use {ENV_TEST_URL} or mongo.url instead)")


def pytest_unconfigure(config):

	server = _servers.pop(config, None)
	if server is not None:
		server.stop()


_servers = {}  # pytest config -> its TestMongo


def with_database(url, name):

	parts = urlsplit(url)

	return urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, parts.fragment))


class TestMongo:
	"""The MongoDB server of a test session, and a new database on it for each test."""


	__test__ = False


	def __init__(self, config):

		self.config = config
		self.token = uuid.uuid4().hex[:8]  # several sessions (and xdist workers) can share a server
		self.count = 0
		self.lock = threading.Lock()
		self.mongod = None
		self.folder = None
		self.error = None
		# Tests' databases are dropped one by one in the background, while the next tests run
		self.drops = ThreadPoolExecutor(max_workers=1, thread_name_prefix="domino-test-drop")


	def server_url(self, app, previous):
		"""The server to use: DOMINO_TEST_MONGO_URL, mongo.connect()'s or the app's mongo.url,
		or else a mongod started now, the first time a test needs one."""

		from . import devmongo, mongo

		url = os.environ.get(ENV_TEST_URL) or (previous if isinstance(previous, str) else None)
		settings = app.settings if app is not None else {}
		if not url:
			url = (settings.get("mongo") or {}).get("url") or os.environ.get("DOMINO_MONGO__URL") or os.environ.get("MONGO_URL")
		if url:
			return url

		if self.config.getoption("no_mongo") or devmongo.disabled_reason(settings):
			raise mongo.MongoNotConfigured(
				"This test uses a named Collection, which is stored in MongoDB, but starting one for "
				"tests is turned off (--no-mongo, DOMINO_NO_MONGO or the setting mongo.auto: false). "
				f"Set {ENV_TEST_URL} to a MongoDB server for tests, e.g. "
				"mongodb://127.0.0.1:27017/?replicaSet=rs0, or use Collection() without a name."
			)

		with self.lock:
			if self.error is None and self.mongod is None:
				self.start(settings)
			if self.error is not None:
				raise mongo.MongoNotConfigured(self.error)

			return self.mongod.url


	def start(self, settings):

		from . import devmongo

		version = str((settings.get("mongo") or {}).get("version") or devmongo.DEFAULT_VERSION)
		self.folder = tempfile.mkdtemp(prefix="domino-test-mongo-")
		mongod = devmongo.DevMongo(self.folder, major=version)
		mongod.dbname = "domino"

		try:
			mongod.start()
		except (devmongo.DevMongoError, OSError) as error:
			mongod.stop()
			# Kept, so the other tests fail straight away instead of trying again
			self.error = (
				f"Couldn't start a MongoDB for the tests: {error}\n"
				f"Set {ENV_TEST_URL} to a MongoDB server for tests (a replica set, so pages update "
				"live), e.g. mongodb://127.0.0.1:27017/?replicaSet=rs0, or pass --no-mongo."
			)
			return

		self.mongod = mongod


	def database_url(self, app, previous):
		"""A database of its own for the next test (MongoDB creates it on first write)."""

		url = self.server_url(app, previous)

		with self.lock:
			self.count += 1
			count = self.count

		from . import mongo

		_, name = mongo.split_url(url)

		return with_database(url, f"{name[:24]}_test_{self.token}_{count}")


	def drop(self, url):

		from . import mongo

		def drop():
			try:
				mongo.drop_database(url)
			except Exception as error:
				print(f"domino: couldn't drop the test database {url}: {error}", file=sys.stderr)

		self.drops.submit(drop)


	def stop(self):

		from . import mongo

		self.drops.shutdown()

		if self.mongod is not None:
			mongo.close()
			self.mongod.stop()
			self.mongod = None

		if self.folder is not None:
			shutil.rmtree(self.folder, ignore_errors=True)
			self.folder = None


class TestDatabase:
	"""One test's MongoDB database, chosen (and the server started) only when it connects."""


	__test__ = False


	def __init__(self, server, previous):

		self.server = server
		self.previous = previous
		self.app = None
		self.url = None


	def __call__(self):

		from . import mongo

		if self.url is None:
			app = self.app
			if app is None and mongo._app is not None:
				app = mongo._app()
			self.url = self.server.database_url(app, self.previous)

		return self.url


	def finish(self):

		from . import mongo

		# The test's change streams stop, without announcing anything to the next test
		mongo.connect(self.previous)

		if self.url is not None:
			self.server.drop(self.url)


@pytest.fixture
def _domino_database(request):

	from . import mongo

	server = _servers.get(request.config)
	if server is None:
		server = _servers[request.config] = TestMongo(request.config)

	database = TestDatabase(server, mongo._url)
	mongo.connect(database)

	yield database

	database.finish()


@pytest.fixture
def domino_db(_domino_database):
	"""This test's MongoDB database (pymongo), the one named Collections use. Empty at the
	start of each test and dropped after it."""

	from . import mongo

	return mongo.database()


@pytest.fixture
def open_page(request, _domino_database):
	"""Open the page this test file is next to (`open_page(id=3)` fills in [id]), or any
	path of its app (`open_page("/about")`). Each call is a new browser tab."""

	target = page_test_target(request.path)
	if target is None:
		raise pytest.UsageError(f"open_page and page only work in tests next to a page: pages/<page>{TEST_SUFFIX}")

	folder, pages, page_file = target
	app = load_app(folder)
	_domino_database.app = app

	# Each test starts with no failed logins or emails counted, like its empty database
	accounts = sys.modules.get("domino.accounts")
	if accounts is not None:
		accounts._failures.clear()
		accounts._mailed.clear()

	def open_(path=None, **params):

		if path is None:
			# The page may be a template: pages/index.html
			if not page_file.is_file() and not page_file.with_suffix(".html").is_file():
				raise pytest.UsageError(f"{request.path.name} tests {page_file.name}, which doesn't exist; pass a path to open_page()")
			path = page_url(pages, page_file, params)

		return app.test_page(path)

	return open_


@pytest.fixture
def page(open_page):
	"""The page this test file is next to, open in a simulated browser."""

	return open_page()


@pytest.fixture
def mail_outbox():
	"""The emails sent during this test (domino.mail.Message: .to, .subject, .text, .html,
	.links). Under pytest mail.send() keeps emails in memory instead of sending them."""

	from . import mail

	mail.outbox.clear()

	yield mail.outbox

	mail.outbox.clear()


def page_url(pages, page_file, params):

	from .pages import url_rule

	rule = url_rule(page_file.relative_to(pages))
	names = re.findall(r"<(?:\w+:)?(\w+)>", rule)
	missing = [name for name in names if name not in params]
	if missing:
		raise pytest.UsageError(f"{page_file.name} has URL parameters; use open_page({', '.join(f'{name}=...' for name in missing)})")

	def fill(match):
		converter, name = match.groups()
		# A [...rest] parameter is a path, so its slashes stay
		return quote(str(params[name]), safe="/" if converter == "path" else "")

	return re.sub(r"<(?:(\w+):)?(\w+)>", fill, rule)
