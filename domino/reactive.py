"""Reactive data, like Meteor's Tracker: reading it in a component's render() subscribes the
component, and changing it re-renders every subscribed component on every open page."""

import logging
import queue
import threading
import uuid
import weakref
from contextlib import contextmanager
from copy import deepcopy


_state = threading.local()

log = logging.getLogger(__name__)


def current_component():
	"""The component whose render() is running in this thread, if any."""

	from .core import render_stack

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
				component.refresh(skip=self.skip_page)
			else:
				component.refresh()


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
	"""Wait until background updates have been sent (useful in tests)."""

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

	component.refresh()


class State:
	"""A single reactive value. Read it with .value (or get()), change it with .value = x (or set())."""


	def __init__(self, value=None):

		self._value = value
		self._dependency = Dependency()


	def get(self):

		self._dependency.depend()

		return self._value


	def set(self, value):

		if value == self._value:
			return

		self._value = value
		self._dependency.changed()


	value = property(get, set)


	def __repr__(self):

		return f"State({self._value!r})"


class Collection:
	"""An in-memory collection of documents (dicts) with a Meteor/MongoDB-like API.

	Every document gets a string "_id". find() returns a reactive cursor: iterating it inside
	render() subscribes the component to changes in the collection.
	"""


	def __init__(self, name=None):

		self.name = name
		self._documents = {}  # _id -> document, in insertion order
		self._lock = threading.RLock()
		self._dependency = Dependency()

		# Matching and sorting per query, reused until the collection changes, since many
		# subscribers usually render the same query after each change
		self._results = {}


	def insert(self, document):

		document = deepcopy(document)
		document.setdefault("_id", uuid.uuid4().hex)

		with self._lock:
			if document["_id"] in self._documents:
				raise ValueError(f"Duplicate _id: {document['_id']!r}")
			self._documents[document["_id"]] = document
			self._results.clear()

		self._dependency.changed()

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

		check_query(query)
		updated = 0

		with self._lock:
			for document in list(self._documents.values()):
				if not matches(document, query):
					continue
				replacement = apply_changes(document, changes)
				self._documents[document["_id"]] = replacement
				updated += 1
				if not multi:
					break
			if updated:
				self._results.clear()

		if updated:
			self._dependency.changed()

		return updated


	def remove(self, query=None):

		check_query(query)

		with self._lock:
			removed = [key for key, document in self._documents.items() if matches(document, query)]
			for key in removed:
				del self._documents[key]
			if removed:
				self._results.clear()

		if removed:
			self._dependency.changed()

		return len(removed)


	def _fetch(self, query, sort, limit):

		check_query(query)
		self._dependency.depend()

		key = repr((query, sort, limit))
		with self._lock:
			documents = self._results.get(key)
			if documents is None:
				documents = sort_documents([document for document in self._documents.values() if matches(document, query)], sort)
				if limit is not None:
					documents = documents[:limit]
				self._results[key] = documents

			# Copies, so callers can't change the stored documents
			return [copy_document(document) for document in documents]


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
