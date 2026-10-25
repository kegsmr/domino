"""Reactive data, like Meteor's Tracker: reading it in a component's render() subscribes the
component, and changing it re-renders every subscribed component on every open page."""

import logging
import queue
import threading
import uuid
import weakref
from contextlib import contextmanager
from copy import deepcopy
from typing import Any, Generic, TypeVar, overload


_state = threading.local()

log = logging.getLogger(__name__)


def current_component():
	"""The component whose render() is running in this thread, if any."""

	from ._core import render_stack

	stack = render_stack()
	if stack:
		return stack[-1][0]

	return None


class Dependency:
	"""Something components can depend on; changed() re-renders them."""


	def __init__(self):

		self.dependents = weakref.WeakSet()
		self.lock = threading.Lock()


	def depend(self):

		# A prediction's reads don't subscribe anything; the real render's do
		if getattr(_state, "overlay", None) is not None:
			return

		component = current_component()
		if component is None:
			return

		with self.lock:
			self.dependents.add(component)
		component.__dependencies__.add(self)


	def forget(self, component):

		with self.lock:
			self.dependents.discard(component)


	def changed(self):

		with self.lock:
			dependents = list(self.dependents)

		for component in dependents:
			schedule(component)


def forget(component):
	"""Drop a component's subscriptions before it renders; rendering subscribes it again."""

	for dependency in component.__dependencies__:
		dependency.forget(component)
	component.__dependencies__.clear()


class Batch:
	"""Changes collected while a batch is open, re-rendered once each when it closes."""


	def __init__(self):

		self.pending = {}  # component -> None; a dict keeps the order and drops repeats
		self.skip_page = None
		self.skip_root = None


	def affected_on(self, page):
		"""The first component changed so far that's shown on `page`, if any."""

		for component in self.pending:
			if page in (component.__pages__ or ()):
				return component

		return None


	def skip(self, page, root):
		"""`root` was just rendered for `page` (e.g. an event response); don't push it there again."""

		self.skip_page = page
		self.skip_root = root


	def flush(self):

		skipped = set()
		if self.skip_root is not None:
			stack = [self.skip_root]
			while stack:
				element = stack.pop()
				if id(element) in skipped or not hasattr(element, "__children__"):
					continue
				skipped.add(id(element))
				stack.extend(element.__children__)

		for component in self.pending:
			if id(component) in skipped:
				component._refresh(skip=self.skip_page)
			else:
				component._refresh()


# Batches flushed in the background, one at a time so updates keep their order
_flushes = queue.Queue()
_worker = None
_worker_lock = threading.Lock()


def _work():

	while True:
		pending = _flushes.get()
		try:
			pending.flush()
		except Exception:
			log.exception("Updating subscribers failed")
		finally:
			_flushes.task_done()


def _flush_in_background(pending):

	global _worker

	with _worker_lock:
		if _worker is None:
			_worker = threading.Thread(target=_work, name="domino-reactive", daemon=True)
			_worker.start()

	_flushes.put(pending)


def wait():
	"""Wait until background updates have been sent (useful in tests), including those for
	changes a MongoDB change stream has yet to announce."""

	from . import mongo
	mongo.wait()

	_flushes.join()


@contextmanager
def batch(background=False):
	"""Re-render each affected component once, after the block, instead of after every change.
	With background=True the re-renders happen on a worker thread, so e.g. the browser that
	made a change gets its response without waiting for every other page to update."""

	outer = getattr(_state, "batch", None)
	if outer is not None:
		yield outer
		return

	current = Batch()
	_state.batch = current
	try:
		yield current
	finally:
		_state.batch = None
		if current.pending and background:
			_flush_in_background(current)
		elif current.pending:
			current.flush()


def schedule(component):

	pending = getattr(_state, "batch", None)
	if pending is not None:
		pending.pending[component] = None
		return

	component._refresh()


class predicting:
	"""Within the block, State changes are kept aside (and dropped after), so a handler can be
	run to see what it would change without changing anything. `values` ({State: value}, a dict
	this keeps the changes in) are what those States read as meanwhile. Gives that dict.

	A class rather than @contextmanager: predicting a component's states runs it many times."""


	def __init__(self, values=None):

		self.overlay = {} if values is None else values


	def __enter__(self):

		_state.overlay = self.overlay
		return self.overlay


	def __exit__(self, *error):

		_state.overlay = None


def is_predicting():

	return getattr(_state, "overlay", None) is not None


# The type of a State's value: State(0) holds an int, so editors know self.count is one
T = TypeVar("T")


class State(Generic[T]):
	"""A reactive value. Read it with .value (or get()), change it with .value = x (or set()).

	As a class attribute of a component it's a value per component instance, read and set like
	a plain attribute (self.count += 1), like React's useState:

		class Counter(t.div):
			count = State(0)
	"""


	def __init__(self, value: T = None):

		self._value = value
		self._dependency = Dependency()
		self._name = None


	def __set_name__(self, owner, name):

		self._name = name


	@overload
	def __get__(self, instance: None, owner: Any) -> "State[T]": ...

	@overload
	def __get__(self, instance: object, owner: Any) -> T: ...

	def __get__(self, instance, owner):

		if instance is None:
			return self

		return self._of(instance).get()


	def __set__(self, instance: object, value: T) -> None:

		self._of(instance).set(value)


	def _of(self, instance):
		"""This attribute's State for one component; the class attribute holds the default."""

		key = f"__state_{self._name}__"
		state = instance.__dict__.get(key)
		if state is None:
			state = State(deepcopy(self._value))
			instance.__dict__[key] = state

		return state


	def get(self) -> T:

		self._dependency.depend()

		overlay = getattr(_state, "overlay", None)
		if overlay is not None and self in overlay:
			return overlay[self]

		return self._value


	def set(self, value: T) -> None:

		# While predicting a handler's outcome, changes go to the overlay and change nothing real
		overlay = getattr(_state, "overlay", None)
		if overlay is not None:
			overlay[self] = value
			return

		# Lists, dicts and sets may have been changed in place, so always count as changed
		if value == self._value and not isinstance(value, (list, dict, set)):
			return

		self._value = value
		self._dependency.changed()


	value = property(get, set)


	def __repr__(self):

		return f"State({self._value!r})"


class Collection:
	"""A collection of documents (dicts) with a Meteor/MongoDB-like API.

	Collection("name") is stored in MongoDB (see domino.mongo); Collection() with no name lives
	in memory, like Meteor's local collections. Every document gets a string "_id" unless it
	has one. find() returns a reactive cursor: iterating it inside render() subscribes the
	component to changes in the collection.
	"""


	def __init__(self, name=None):

		self.name = name
		self._store = None
		self._lock = threading.RLock()
		self._dependency = Dependency()

		# Query results reused until the collection changes, since many subscribers usually
		# render the same query after each change. The version guards against caching a
		# result read before a change that finished while it was being read.
		self._results = {}
		self._version = 0


	def store(self):
		"""Where the documents live, created on first use (named collections connect to MongoDB)."""

		with self._lock:
			if self._store is None and self.name is None:
				self._store = MemoryStore()
			elif self._store is None or getattr(self._store, "stale", False):
				# A new one after domino.mongo.connect() (each test gets its own database);
				# results read from the old database are forgotten
				from .mongo import MongoStore
				self._results.clear()
				self._version += 1
				self._store = MongoStore(self.name, self.changed)

		return self._store


	def changed(self):
		"""Forget cached results and re-render subscribers. Called after writes, and by the
		MongoDB store when another process changes the collection."""

		with self._lock:
			self._results.clear()
			self._version += 1

		self._dependency.changed()


	def _wrote(self):

		# A MongoDB change stream reports our own writes too; let it announce them so each
		# change re-renders subscribers once. Cached results are dropped right away, so the
		# writer's own next read already sees the change.
		if getattr(self._store, "watching", False):
			with self._lock:
				self._results.clear()
				self._version += 1
			return

		self.changed()


	def insert(self, document):

		document = deepcopy(document)
		document.setdefault("_id", uuid.uuid4().hex)

		self.store().insert(document)
		self._wrote()

		return document["_id"]


	def find(self, query=None, sort=None, limit=None):

		return Cursor(self, query, sort, limit)


	def find_one(self, query=None):

		for document in self.find(query, limit=1):
			return document

		return None


	def count(self, query=None):

		return len(self.find(query).fetch())


	def update(self, query, changes, multi=False):
		"""Apply `changes` ($set, $unset, $inc, $push, $pull, or a whole replacement document)
		to the first matching document, or every one with multi=True. Returns the count."""

		updated = self.store().update(query or {}, changes, multi)
		if updated:
			self._wrote()

		return updated


	def remove(self, query=None):

		removed = self.store().remove(query or {})
		if removed:
			self._wrote()

		return removed


	def raw_collection(self):
		"""The pymongo collection behind a named Collection, like Meteor's rawCollection(): for
		what Collection doesn't do, such as indexes and aggregation. Writes made through it still
		update open pages, since MongoDB's change stream reports them."""

		if self.name is None:
			raise TypeError('Collection() without a name lives in memory, so it has no MongoDB collection; name it: Collection("tasks")')

		return self.store().collection


	def raw_database(self):
		"""The pymongo database a named Collection is in, like Meteor's rawDatabase()."""

		return self.raw_collection().database


	def _fetch(self, query, sort, limit):

		store = self.store()
		self._dependency.depend()

		key = repr((query, sort, limit))
		with self._lock:
			documents = self._results.get(key)
			version = self._version

		if documents is None:
			documents = store.find(query or {}, sort, limit)
			with self._lock:
				if self._version == version:
					self._results[key] = documents

		# Copies, so callers can't change the stored documents or the cached results
		return [copy_document(document) for document in documents]


class MemoryStore:
	"""Documents kept in this process (for Collection() without a name)."""


	def __init__(self):

		self.documents = {}  # _id -> document, in insertion order
		self.lock = threading.Lock()


	def insert(self, document):

		with self.lock:
			if document["_id"] in self.documents:
				raise ValueError(f"Duplicate _id: {document['_id']!r}")
			self.documents[document["_id"]] = document


	def find(self, query, sort, limit):

		check_query(query)

		with self.lock:
			documents = [document for document in self.documents.values() if matches(document, query)]

		documents = sort_documents(documents, sort)
		if limit is not None:
			documents = documents[:limit]

		return documents


	def update(self, query, changes, multi):

		check_query(query)
		updated = 0

		with self.lock:
			for document in list(self.documents.values()):
				if not matches(document, query):
					continue
				self.documents[document["_id"]] = apply_changes(document, changes)
				updated += 1
				if not multi:
					break

		return updated


	def remove(self, query):

		check_query(query)

		with self.lock:
			removed = [key for key, document in self.documents.items() if matches(document, query)]
			for key in removed:
				del self.documents[key]

		return len(removed)


class Cursor:
	"""The documents a query matches, read when iterated (so reads inside render() subscribe)."""


	def __init__(self, collection, query=None, sort=None, limit=None):

		self.collection = collection
		self.query = query
		self.sort = sort
		self.limit = limit


	def fetch(self):

		return self.collection._fetch(self.query, self.sort, self.limit)


	def count(self):

		return len(self.fetch())


	def __iter__(self):

		return iter(self.fetch())


	def __len__(self):

		return self.count()


MISSING = object()


def copy_document(value):
	"""A deep copy of JSON-like data, much faster than copy.deepcopy for documents."""

	if isinstance(value, dict):
		return {key: copy_document(item) for key, item in value.items()}
	if isinstance(value, list):
		return [copy_document(item) for item in value]
	if isinstance(value, (str, int, float, bool, type(None))):
		return value

	return deepcopy(value)


def get_path(document, path):
	"""document["a"]["b"] for the path "a.b", or MISSING."""

	value = document
	for part in path.split("."):
		if not isinstance(value, dict) or part not in value:
			return MISSING
		value = value[part]

	return value


def matches(document, query):
	"""Whether `document` matches a MongoDB-style query (a supported subset)."""

	for key, condition in (query or {}).items():
		if key == "$and":
			if not all(matches(document, part) for part in condition):
				return False
		elif key == "$or":
			if not any(matches(document, part) for part in condition):
				return False
		elif not matches_value(get_path(document, key), condition):
			return False

	return True


def matches_value(value, condition):

	if isinstance(condition, dict) and condition and all(key.startswith("$") for key in condition):
		return all(matches_operator(value, operator, operand) for operator, operand in condition.items())

	# Like MongoDB, a list matches when it contains the value
	if isinstance(value, list) and not isinstance(condition, list):
		return condition in value

	return value is not MISSING and value == condition


QUERY_OPERATORS = {"$eq", "$ne", "$gt", "$gte", "$lt", "$lte", "$in", "$nin", "$exists"}


def check_query(query):
	"""Raise for operators this collection doesn't support, even if nothing would match."""

	for key, condition in (query or {}).items():
		if key in ("$and", "$or"):
			for part in condition:
				check_query(part)
		elif key.startswith("$"):
			raise ValueError(f"Unsupported query operator: {key}")
		elif isinstance(condition, dict):
			for operator in condition:
				if operator.startswith("$") and operator not in QUERY_OPERATORS:
					raise ValueError(f"Unsupported query operator: {operator}")


def matches_operator(value, operator, operand):

	# Fail loudly instead of quietly matching nothing
	if operator not in QUERY_OPERATORS:
		raise ValueError(f"Unsupported query operator: {operator}")

	if operator == "$exists":
		return (value is not MISSING) == bool(operand)
	if operator == "$ne":
		return not matches_value(value, operand)
	if operator == "$in":
		return any(matches_value(value, option) for option in operand)
	if operator == "$nin":
		return not any(matches_value(value, option) for option in operand)
	if value is MISSING or value is None:
		return False
	if operator == "$eq":
		return value == operand

	comparisons = {
		"$gt": lambda: value > operand,
		"$gte": lambda: value >= operand,
		"$lt": lambda: value < operand,
		"$lte": lambda: value <= operand,
	}

	try:
		return comparisons[operator]()
	except TypeError:
		return False


def apply_changes(document, changes):

	if not any(key.startswith("$") for key in changes):
		# A replacement document keeps its _id
		replacement = deepcopy(changes)
		replacement["_id"] = document["_id"]
		return replacement

	document = deepcopy(document)
	for operator, fields in changes.items():
		for path, operand in fields.items():
			parent, key = parent_of(document, path)
			if operator == "$set":
				parent[key] = deepcopy(operand)
			elif operator == "$unset":
				parent.pop(key, None)
			elif operator == "$inc":
				parent[key] = parent.get(key, 0) + operand
			elif operator == "$push":
				parent.setdefault(key, []).append(deepcopy(operand))
			elif operator == "$pull":
				parent[key] = [item for item in parent.get(key, []) if not matches_value(item, operand)]
			else:
				raise ValueError(f"Unsupported update operator: {operator}")

	return document


def parent_of(document, path):
	"""The dict holding the last part of `path` (created as needed) and that last key."""

	parts = path.split(".")
	parent = document
	for part in parts[:-1]:
		parent = parent.setdefault(part, {})

	return parent, parts[-1]


def sort_documents(documents, sort):
	"""Sort by "field", or a list of (field, 1 or -1) pairs like MongoDB."""

	if not sort:
		return documents
	if isinstance(sort, str):
		sort = [(sort, 1)]

	# Stable sorts from the last key to the first give a multi-key sort; missing values first
	for field, direction in reversed(sort):
		documents.sort(key=lambda document: sort_key(get_path(document, field)), reverse=direction < 0)

	return documents


def sort_key(value):

	if value is MISSING or value is None:
		return (0, 0)

	return (1, value)
