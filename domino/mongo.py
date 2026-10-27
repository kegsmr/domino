"""MongoDB storage for named Collections.

The connection URL comes from the app's settings (`mongo.url`, so also the environment variable
DOMINO_MONGO__URL), or `connect(url)`. When MongoDB runs as a replica set (as `domino run`
starts it), a change stream per collection re-renders subscribers when any process changes it.
"""

import logging
import os
import threading
import time
import weakref
from contextlib import contextmanager
from urllib.parse import unquote, urlsplit, urlunsplit


log = logging.getLogger(__name__)

_lock = threading.Lock()
_url = None
_client = None
_client_server = None  # the URL _client was made for, without its database
_database = None
_app = None
_generation = 0  # bumped by connect(): stores made before it are stale
_stores = weakref.WeakSet()


class MongoNotConfigured(RuntimeError):
	"""No MongoDB URL was configured."""


def use_app(app):
	"""Read the URL from this app's settings (Domino() calls this)."""

	global _app

	_app = weakref.ref(app)


def connect(url):
	"""Use MongoDB at `url` from now on (the database name comes from the URL, default "domino").
	`url` can also be a function returning it, called on first use: the pytest plugin passes one,
	so that MongoDB is only started for tests that use it.

	Collections switch to the new database the next time they're used, and their change streams
	on the old one stop without announcing anything more."""

	global _url, _database, _generation

	# The client is kept for the same server (another database on it needs no new connections).
	# One for another server replaces it, unclosed: it's closed when nothing uses it any more
	with _lock:
		_url = url
		_database = None
		_generation += 1


def close():
	"""Close the connection (the pytest plugin does before it stops the MongoDB it started)."""

	global _client, _client_server, _database, _generation

	with _lock:
		client = _client
		_client = _client_server = _database = None
		_generation += 1

	if client is not None:
		client.close()


def split_url(url):
	"""(the URL without its database, the database name) for a MongoDB URL."""

	parts = urlsplit(url)
	name = unquote(parts.path.lstrip("/")) or "domino"

	return urlunsplit((parts.scheme, parts.netloc, "/", parts.query, parts.fragment)), name


def drop_database(url):
	"""Drop the database `url` names, if this process is connected to its server."""

	server, name = split_url(url)
	with _lock:
		client = _client if _client_server == server else None

	if client is not None:
		client.drop_database(name)


def wait(timeout=5):
	"""Wait until change streams have announced this process's writes, so subscribers were
	re-rendered (domino.wait() calls this)."""

	for store in list(_stores):
		store.wait(timeout)


def configured_url():

	if callable(_url):
		return _url()
	if _url:
		return _url

	app = _app() if _app else None
	if app is not None:
		url = (app.settings.get("mongo") or {}).get("url")
		if url:
			return url

	return os.environ.get("DOMINO_MONGO__URL") or os.environ.get("MONGO_URL")


def database():
	"""The connected database, connecting on first use."""

	global _client, _client_server, _database

	with _lock:
		if _database is not None:
			return _database

		url = configured_url()
		if not url:
			raise MongoNotConfigured(
				"Named Collections are stored in MongoDB, but no MongoDB is configured. Run the app "
				"with `domino run` or app.run(debug=True) to start one locally, or set mongo.url in "
				"settings.json (or DOMINO_MONGO__URL). Use Collection() without a name for an "
				"in-memory collection."
			)

		try:
			import pymongo
		except ImportError:
			raise MongoNotConfigured("MongoDB needs pymongo: pip install pymongo") from None

		# Made with the whole URL, so credentials are checked against its database as usual
		server, name = split_url(url)
		if _client is None or _client_server != server:
			_client = pymongo.MongoClient(url)
			_client_server = server
		_database = _client[name]

		return _database


def sort_spec(sort):
	"""Domino's sort ("field" or [(field, 1 or -1), ...]) as pymongo expects it."""

	if not sort:
		return None
	if isinstance(sort, str):
		return [(sort, 1)]

	return [(field, direction) for field, direction in sort]


def changed_documents(change):
	"""[(_id, the document now, or None if it's gone)] for a change stream event, or None when
	it isn't about one document (a dropped collection), so every subscriber re-renders."""

	if change.get("operationType") not in ("insert", "update", "replace", "delete"):
		return None

	key = change.get("documentKey") or {}
	if "_id" not in key:
		return None

	# An update's document is looked up after the change, so None if it was deleted since
	return [(key["_id"], change.get("fullDocument"))]


class MongoStore:
	"""A Collection's documents in a MongoDB collection of the same name."""


	def __init__(self, name, changed):

		self.name = name
		database()  # fail early, with a clear message, when MongoDB isn't configured
		self.generation = _generation
		self.watching = False

		# Changes are only judged by query (see domino.reactive.Read) when MongoDB compares
		# strings as Python does: a default collation (case-insensitive, say) changes that
		self.matching = "plain"
		try:
			if self.collection.options().get("collation"):
				self.matching = None
		except Exception:
			self.matching = None

		# Cluster times of this process's last write and of the last change the stream
		# announced, for wait()
		self._written = None
		self._seen = None
		self._caught_up = threading.Condition()
		_stores.add(self)

		# Weak, so a collection nobody uses any more doesn't keep a watcher alive
		self._changed = weakref.WeakMethod(changed)
		self._started = threading.Event()
		threading.Thread(target=self._watch, name=f"domino-watch-{name}", daemon=True).start()

		# Give the change stream a moment to open, so a write made right away is seen by it
		self._started.wait(0.5)


	def _watch(self):

		import pymongo.errors

		# Updates come with the document as it is now, to tell which pages they affect. What
		# changed in it isn't needed: leaving it out keeps an event with a large document under
		# MongoDB's size limit (an event over it would end the stream)
		pipeline = [{"$project": {"updateDescription": 0}}]

		resume = None
		while not self.stale:
			try:
				with self.collection.watch(pipeline, resume_after=resume, full_document="updateLookup") as stream:
					self.watching = True
					self._started.set()
					while stream.alive:
						# None after a second without changes, so a stale watcher ends soon
						change = stream.try_next()
						# Stale: connect() switched databases, e.g. for the next test
						if self.stale:
							return
						if change is None:
							continue
						resume = stream.resume_token
						changed = self._changed()
						if changed is None:
							return
						changed(changed_documents(change))
						with self._caught_up:
							self._seen = change.get("clusterTime")
							self._caught_up.notify_all()
						# A dropped collection or database ends the stream for good, and it
						# can't be resumed; start a new one so a recreated collection stays live
						if change.get("operationType") == "invalidate":
							resume = None
							break
			except pymongo.errors.OperationFailure as error:
				if self.stale:
					return
				# Change streams need a replica set; without one, only this process's own
				# writes re-render subscribers
				self.watching = False
				self._started.set()
				log.warning("No change stream for %r (%s): changes from other processes won't update pages live", self.name, error)
				return
			except pymongo.errors.PyMongoError:
				self.watching = False
				if self.stale:
					return
				log.exception("Change stream for %r stopped; reconnecting", self.name)
				time.sleep(1)


	@property
	def stale(self):
		"""Whether connect() was called since this store was made (Collection makes a new one)."""

		return self.generation != _generation


	def wait(self, timeout=5):

		with self._caught_up:
			self._caught_up.wait_for(lambda: not self.watching or self.stale or self._written is None or (self._seen is not None and self._seen >= self._written), timeout)


	@contextmanager
	def _session(self):

		# Its operation time is the write's cluster time, which the change stream reports
		with self.collection.database.client.start_session() as session:
			yield session


	def _wrote(self, session):

		if self.watching and session.operation_time is not None:
			with self._caught_up:
				if self._written is None or session.operation_time > self._written:
					self._written = session.operation_time


	@property
	def collection(self):

		# Looked up each time, so connect() to another server takes effect everywhere
		return database()[self.name]


	def insert(self, document):

		with self._session() as session:
			self.collection.insert_one(document, session=session)
			self._wrote(session)


	def find(self, query, sort, limit):

		cursor = self.collection.find(query)
		spec = sort_spec(sort)
		if spec:
			cursor = cursor.sort(spec)
		if limit is not None:
			cursor = cursor.limit(limit)

		return list(cursor)


	def update(self, query, changes, multi, changed=None):
		"""Returns the count. `changed` is left empty: the change stream says what changed."""

		with self._session() as session:
			if not any(key.startswith("$") for key in changes):
				result = self.collection.replace_one(query, changes, session=session)
			elif multi:
				result = self.collection.update_many(query, changes, session=session)
			else:
				result = self.collection.update_one(query, changes, session=session)

			# An update that changes nothing makes no change event to wait for
			if result.modified_count:
				self._wrote(session)

		# Matched, not modified, like the in-memory store: an update that changes nothing still counts
		return result.matched_count


	def remove(self, query, changed=None):

		with self._session() as session:
			deleted = self.collection.delete_many(query, session=session).deleted_count
			if deleted:
				self._wrote(session)

		return deleted
