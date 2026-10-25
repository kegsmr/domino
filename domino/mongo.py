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


log = logging.getLogger(__name__)

_lock = threading.Lock()
_url = None
_client = None
_database = None
_app = None


class MongoNotConfigured(RuntimeError):
	"""No MongoDB URL was configured."""


def use_app(app):
	"""Read the URL from this app's settings (Domino() calls this)."""

	global _app

	_app = weakref.ref(app)


def connect(url):
	"""Use MongoDB at `url` from now on (the database name comes from the URL, default "domino")."""

	global _url, _client, _database

	# The old client isn't closed: change stream watchers may still be reading from it, and
	# it's closed when nothing uses it any more
	with _lock:
		_url = url
		_client = None
		_database = None


def configured_url():

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

	global _client, _database

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

		_client = pymongo.MongoClient(url)
		_database = _client.get_default_database(default="domino")

		return _database


def sort_spec(sort):
	"""Domino's sort ("field" or [(field, 1 or -1), ...]) as pymongo expects it."""

	if not sort:
		return None
	if isinstance(sort, str):
		return [(sort, 1)]

	return [(field, direction) for field, direction in sort]


class MongoStore:
	"""A Collection's documents in a MongoDB collection of the same name."""


	def __init__(self, name, changed):

		self.name = name
		database()  # fail early, with a clear message, when MongoDB isn't configured
		self.watching = False
		self._watch_failed = False

		# Weak, so a collection nobody uses any more doesn't keep a watcher alive
		self._changed = weakref.WeakMethod(changed)
		threading.Thread(target=self._watch, name=f"domino-watch-{name}", daemon=True).start()

		# Give the change stream a moment to open, so a write made right away is seen by it
		for _ in range(50):
			if self.watching or self._watch_failed:
				break
			time.sleep(0.01)


	def _watch(self):

		import pymongo.errors

		resume = None
		while True:
			try:
				with self.collection.watch(resume_after=resume) as stream:
					self.watching = True
					for change in stream:
						resume = stream.resume_token
						changed = self._changed()
						if changed is None:
							return
						changed()
						# A dropped collection or database ends the stream for good, and it
						# can't be resumed; start a new one so a recreated collection stays live
						if change.get("operationType") == "invalidate":
							resume = None
							break
			except pymongo.errors.OperationFailure as error:
				# Change streams need a replica set; without one, only this process's own
				# writes re-render subscribers
				self.watching = False
				self._watch_failed = True
				log.warning("No change stream for %r (%s): changes from other processes won't update pages live", self.name, error)
				return
			except pymongo.errors.PyMongoError:
				self.watching = False
				log.exception("Change stream for %r stopped; reconnecting", self.name)
				time.sleep(1)


	@property
	def collection(self):

		# Looked up each time, so connect() to another server takes effect everywhere
		return database()[self.name]


	def insert(self, document):

		self.collection.insert_one(document)


	def find(self, query, sort, limit):

		cursor = self.collection.find(query)
		spec = sort_spec(sort)
		if spec:
			cursor = cursor.sort(spec)
		if limit is not None:
			cursor = cursor.limit(limit)

		return list(cursor)


	def update(self, query, changes, multi):

		# Matched, not modified, like the in-memory store: an update that changes nothing still counts
		if not any(key.startswith("$") for key in changes):
			return self.collection.replace_one(query, changes).matched_count
		if multi:
			return self.collection.update_many(query, changes).matched_count

		return self.collection.update_one(query, changes).matched_count


	def remove(self, query):

		return self.collection.delete_many(query).deleted_count
