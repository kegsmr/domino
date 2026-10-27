"""A component re-renders only when a change can change what its queries found (#47)."""

import time
import uuid

import pytest

import domino.tags as t
from domino import Collection, Domino, mongo, wait
from domino.components import Document
from domino.mongo import changed_documents
from domino.reactive import may_match


# The apps a test showed, so their pages (and components) stay alive until it ends
apps = []


@pytest.fixture(autouse=True)
def keep_apps():

	yield
	apps.clear()


def show(query, collection, limit=None, sort="n"):
	"""A page whose component lists what `query` finds; returns the list of its renders."""

	renders = []

	class Found(t.div):

		def render(self):
			found = collection.find(query, sort=sort, limit=limit).fetch()
			renders.append([document["text"] for document in found])
			self([t.li() [document["text"]] for document in found])

	app = Domino(__name__)
	apps.append(app)

	@app.route("/")
	def index():
		return Document() [Found()]

	assert app.test_client().get("/").status_code == 200
	renders.clear()

	return renders


def settled():
	"""Wait for the change stream to announce writes and their re-renders to finish."""

	wait()
	time.sleep(0.2)
	wait()


def unique_name():

	return f"test_{uuid.uuid4().hex[:8]}"


@pytest.fixture(params=["memory", pytest.param("mongo", marks=pytest.mark.mongo)])
def tasks(request):
	"""A collection of tasks in memory and, with MongoDB, a named one."""

	if request.param == "memory":
		return Collection()

	return watched(Collection(unique_name()))


def watched(collection):
	"""`collection`, once its change stream is open: until then MongoDB's updates and deletes
	can't say which documents they changed, so they re-render every subscriber."""

	deadline = time.monotonic() + 10
	while not collection.store().watching:
		assert time.monotonic() < deadline, "the change stream didn't open"
		time.sleep(0.02)

	return collection


def test_a_change_outside_the_result_does_not_re_render(tasks):

	done = tasks.insert({"text": "done", "done": True, "n": 1})
	renders = show({"done": False}, tasks)

	tasks.update({"_id": done}, {"$set": {"text": "still done"}})
	tasks.insert({"text": "also done", "done": True, "n": 2})
	tasks.remove({"_id": done})
	settled()

	assert renders == []


def test_a_document_entering_the_result_re_renders(tasks):

	done = tasks.insert({"text": "later", "done": True, "n": 1})
	renders = show({"done": False}, tasks)

	tasks.insert({"text": "new", "done": False, "n": 2})
	settled()
	assert renders[-1] == ["new"]

	tasks.update({"_id": done}, {"$set": {"done": False}})
	settled()
	assert renders[-1] == ["later", "new"]


def test_a_document_leaving_or_changing_in_the_result_re_renders(tasks):

	first = tasks.insert({"text": "first", "done": False, "n": 1})
	second = tasks.insert({"text": "second", "done": False, "n": 2})
	renders = show({"done": False}, tasks)

	tasks.update({"_id": first}, {"$set": {"text": "first!"}})
	settled()
	assert renders[-1] == ["first!", "second"]

	tasks.update({"_id": first}, {"$set": {"done": True}})
	settled()
	assert renders[-1] == ["second"]

	tasks.remove({"_id": second})
	settled()
	assert renders[-1] == []


def test_a_limited_query_re_renders_when_a_matching_document_may_enter_it(tasks):

	for n in range(3):
		tasks.insert({"text": f"task {n}", "done": False, "n": n})
	renders = show({"done": False}, tasks, limit=2)

	# Removing one in the top two lets the third in
	tasks.remove({"n": 0})
	settled()
	assert renders[-1] == ["task 1", "task 2"]

	# One that sorts first enters
	tasks.insert({"text": "urgent", "done": False, "n": -1})
	settled()
	assert renders[-1] == ["urgent", "task 1"]

	count = len(renders)
	tasks.insert({"text": "done", "done": True, "n": -2})
	settled()
	assert len(renders) == count


def test_each_component_re_renders_for_its_own_query(tasks):

	open_renders = show({"done": False}, tasks)
	done_renders = show({"done": True}, tasks)

	tasks.insert({"text": "open", "done": False, "n": 1})
	settled()

	assert open_renders == [["open"]]
	assert done_renders == []


def test_writes_in_a_batch_re_render_once(tasks):

	from domino import batch

	renders = show({"done": False}, tasks)

	with batch():
		tasks.insert({"text": "a", "done": False, "n": 1})
		tasks.insert({"text": "b", "done": True, "n": 2})
	settled()

	assert renders[-1] == ["a"]
	assert len(renders) <= 2


def test_a_query_without_a_filter_re_renders_on_every_change(tasks):

	renders = show(None, tasks)

	tasks.insert({"text": "any", "done": True, "n": 1})
	settled()

	assert renders[-1] == ["any"]


# In MongoDB


@pytest.mark.mongo
def test_queries_mongodb_runs_differently_re_render_on_every_change():

	tasks = watched(Collection(unique_name()))
	regex = show({"text": {"$regex": "^a"}}, tasks)
	in_list = show({"tags": "x"}, tasks)

	# Neither matches, but matches() can't tell for $regex, or for a field holding a list
	tasks.insert({"text": "b", "tags": ["y"], "n": 1})
	settled()

	assert regex == [[]]
	assert in_list == [[]]


@pytest.mark.mongo
def test_writes_from_another_process_re_render_only_affected_pages():

	name = unique_name()
	tasks = watched(Collection(name))
	renders = show({"done": False}, tasks)

	# Written straight to MongoDB, like another server process would
	mongo.database()[name].insert_one({"_id": "elsewhere", "text": "done elsewhere", "done": True, "n": 1})
	settled()
	assert renders == []

	mongo.database()[name].update_one({"_id": "elsewhere"}, {"$set": {"done": False}})
	settled()
	assert renders[-1] == ["done elsewhere"]

	mongo.database()[name].delete_one({"_id": "elsewhere"})
	settled()
	assert renders[-1] == []


@pytest.mark.mongo
def test_dropping_the_collection_re_renders_everything():

	name = unique_name()
	tasks = watched(Collection(name))
	tasks.insert({"text": "kept", "done": True, "n": 1})
	settled()
	renders = show({"done": False}, tasks)

	mongo.database()[name].drop()
	settled()

	assert renders


# Matching


def test_may_match_in_memory_is_exact():

	assert may_match({"done": True}, {"done": False}) is False
	assert may_match({"done": False}, {"done": False}) is True
	assert may_match({"tags": ["a", "b"]}, {"tags": "c"}) is False
	assert may_match({"n": 5}, {"n": {"$gt": 3, "$lt": 10}}) is True
	assert may_match({"n": 5}, {"$or": [{"n": 1}, {"n": 2}]}) is False


def test_may_match_in_mongodb_decides_only_plain_values():

	# Plain values, as MongoDB would
	assert may_match({"done": True}, {"done": False}, exact=False) is False
	assert may_match({"n": 5}, {"n": {"$gt": 6}}, exact=False) is False
	assert may_match({"a": {"b": 1}}, {"a.b": 2}, exact=False) is False
	assert may_match({"name": "x"}, {"name": {"$in": ["y", "z"]}}, exact=False) is False
	assert may_match({}, {"owner": "me"}, exact=False) is False

	# MongoDB looks inside lists, matches a missing field with null, and has more operators
	assert may_match({"n": [1, 10]}, {"n": {"$gt": 5}}, exact=False) is True
	assert may_match({"items": [{"name": "a"}]}, {"items.name": "a"}, exact=False) is True
	assert may_match({"items": [{"name": "a"}]}, {"items.0.name": "b"}, exact=False) is True
	assert may_match({}, {"deleted": None}, exact=False) is True
	assert may_match({"text": "b"}, {"text": {"$regex": "^a"}}, exact=False) is True
	assert may_match({"text": "b"}, {"$nor": [{"text": "a"}]}, exact=False) is True

	# Other types compare in MongoDB's own ways
	from datetime import datetime, timezone
	assert may_match({"at": datetime(2026, 1, 1)}, {"at": datetime(2026, 1, 1, tzinfo=timezone.utc)}, exact=False) is True
	assert may_match({"a": {"b": 1}}, {"a": {"b": 1, "c": 2}}, exact=False) is True


def test_may_match_in_mongodb_minds_booleans_and_nan():

	assert may_match({"done": 1}, {"done": {"$ne": True}}, exact=False) is True
	assert may_match({"done": True}, {"done": {"$nin": [1]}}, exact=False) is True
	assert may_match({"score": float("nan")}, {"score": float("nan")}, exact=False) is True
	assert may_match({"done": False}, {"done": {"$ne": False}}, exact=False) is False
	assert may_match({"n": 2}, {"n": {"$exists": False}}, exact=False) is False


def test_change_stream_events_name_their_document():

	document = {"_id": "a", "done": True}

	assert changed_documents({"operationType": "insert", "documentKey": {"_id": "a"}, "fullDocument": document}) == [("a", document)]
	assert changed_documents({"operationType": "update", "documentKey": {"_id": "a"}, "fullDocument": None}) == [("a", None)]
	assert changed_documents({"operationType": "delete", "documentKey": {"_id": "a"}}) == [("a", None)]
	assert changed_documents({"operationType": "drop"}) is None
	assert changed_documents({"operationType": "invalidate"}) is None


@pytest.mark.mongo
def test_a_number_written_where_a_boolean_was_expected_re_renders():

	name = unique_name()
	tasks = watched(Collection(name))
	renders = show({"done": {"$ne": True}}, tasks)

	# In MongoDB 1 isn't True, so this one is not done
	mongo.database()[name].insert_one({"_id": "x", "text": "one", "done": 1, "n": 1})
	settled()

	assert renders[-1] == ["one"]


@pytest.mark.mongo
def test_nan_re_renders():

	tasks = watched(Collection(unique_name()))
	renders = show({"score": float("nan")}, tasks)

	# MongoDB's queries find NaN with NaN
	tasks.insert({"text": "nan", "score": float("nan"), "n": 1})
	settled()

	assert renders[-1] == ["nan"]


@pytest.mark.mongo
def test_a_collection_with_a_collation_re_renders_on_every_change():

	from pymongo.collation import Collation

	name = unique_name()
	mongo.database().create_collection(name, collation=Collation("en", strength=2))
	tasks = watched(Collection(name))
	renders = show({"text": "ada"}, tasks)

	# Case-insensitive: "Ada" is found by "ada"
	tasks.insert({"text": "Ada", "n": 1})
	settled()

	assert renders[-1] == ["Ada"]


@pytest.mark.mongo
def test_a_shared_component_shown_on_other_pages_stays_up_to_date(monkeypatch):

	import threading
	from domino.testing import TestPage

	tasks = watched(Collection(unique_name()))
	tasks.insert({"text": "a", "done": False})
	tasks.insert({"text": "b", "done": False})
	settled()

	class Board(t.ul):

		def render(self):
			return [t.li() [task["text"], t.button(on_click=self.finish_first) ["Done"]] for task in tasks.find({"done": False}, sort="text")]

		def finish_first(self):
			tasks.update({"done": False}, {"$set": {"done": True}})

	# One instance on every page, like a board everyone sees
	board = Board()
	app = Domino(__name__)
	apps.append(app)

	@app.route("/")
	def index():
		return Document() [board]

	first = TestPage(app)
	second = TestPage(app)

	# The change stream announces the change only after the click's response
	gate = threading.Event()
	announce = mongo.changed_documents

	def later(change):
		gate.wait(1)
		return announce(change)

	monkeypatch.setattr(mongo, "changed_documents", later)
	first.click("button")
	gate.set()
	settled()

	assert first.sync().text().count("Done") == 1
	assert second.sync().text().count("Done") == 1


@pytest.mark.mongo
def test_a_large_document_keeps_the_change_stream_alive():

	name = unique_name()
	tasks = watched(Collection(name))
	mongo.database()[name].insert_one({"_id": "big", "text": "big", "done": True, "n": 1, "a": "x" * (8 * 1024 * 1024)})
	settled()
	renders = show({"done": False}, tasks)

	# The document after this is 15 MB: with what changed in it as well, the event would be
	# over MongoDB's 16 MB limit
	mongo.database()[name].update_one({"_id": "big"}, {"$set": {"done": False, "b": "y" * (7 * 1024 * 1024)}})
	settled()
	assert renders[-1] == ["big"]

	mongo.database()[name].insert_one({"_id": "small", "text": "small", "done": False, "n": 2})
	settled()
	assert tasks.store().watching
	assert renders[-1] == ["big", "small"]


# Matching


def test_may_match_in_memory_is_exact():

	assert may_match({"done": True}, {"done": False}) is False
	assert may_match({"done": False}, {"done": False}) is True
	assert may_match({"tags": ["a", "b"]}, {"tags": "c"}) is False
	assert may_match({"n": 5}, {"n": {"$gt": 3, "$lt": 10}}) is True
	assert may_match({"n": 5}, {"$or": [{"n": 1}, {"n": 2}]}) is False


def test_may_match_in_mongodb_decides_only_plain_values():

	# Plain values, as MongoDB would
	assert may_match({"done": True}, {"done": False}, exact=False) is False
	assert may_match({"n": 5}, {"n": {"$gt": 6}}, exact=False) is False
	assert may_match({"a": {"b": 1}}, {"a.b": 2}, exact=False) is False
	assert may_match({"name": "x"}, {"name": {"$in": ["y", "z"]}}, exact=False) is False
	assert may_match({}, {"owner": "me"}, exact=False) is False

	# MongoDB looks inside lists, matches a missing field with null, and has more operators
	assert may_match({"n": [1, 10]}, {"n": {"$gt": 5}}, exact=False) is True
	assert may_match({"items": [{"name": "a"}]}, {"items.name": "a"}, exact=False) is True
	assert may_match({"items": [{"name": "a"}]}, {"items.0.name": "b"}, exact=False) is True
	assert may_match({}, {"deleted": None}, exact=False) is True
	assert may_match({"text": "b"}, {"text": {"$regex": "^a"}}, exact=False) is True
	assert may_match({"text": "b"}, {"$nor": [{"text": "a"}]}, exact=False) is True

	# Other types compare in MongoDB's own ways
	from datetime import datetime, timezone
	assert may_match({"at": datetime(2026, 1, 1)}, {"at": datetime(2026, 1, 1, tzinfo=timezone.utc)}, exact=False) is True
	assert may_match({"a": {"b": 1}}, {"a": {"b": 1, "c": 2}}, exact=False) is True


def test_may_match_in_mongodb_minds_booleans_and_nan():

	assert may_match({"done": 1}, {"done": {"$ne": True}}, exact=False) is True
	assert may_match({"done": True}, {"done": {"$nin": [1]}}, exact=False) is True
	assert may_match({"score": float("nan")}, {"score": float("nan")}, exact=False) is True
	assert may_match({"done": False}, {"done": {"$ne": False}}, exact=False) is False
	assert may_match({"n": 2}, {"n": {"$exists": False}}, exact=False) is False


def test_change_stream_events_name_their_document():

	document = {"_id": "a", "done": True}

	assert changed_documents({"operationType": "insert", "documentKey": {"_id": "a"}, "fullDocument": document}) == [("a", document)]
	assert changed_documents({"operationType": "update", "documentKey": {"_id": "a"}, "fullDocument": None}) == [("a", None)]
	assert changed_documents({"operationType": "delete", "documentKey": {"_id": "a"}}) == [("a", None)]
	assert changed_documents({"operationType": "drop"}) is None
	assert changed_documents({"operationType": "invalidate"}) is None


@pytest.mark.mongo
def test_a_number_written_where_a_boolean_was_expected_re_renders():

	name = unique_name()
	tasks = watched(Collection(name))
	renders = show({"done": {"$ne": True}}, tasks)

	# In MongoDB 1 isn't True, so this one is not done
	mongo.database()[name].insert_one({"_id": "x", "text": "one", "done": 1, "n": 1})
	settled()

	assert renders[-1] == ["one"]


@pytest.mark.mongo
def test_nan_re_renders():

	tasks = watched(Collection(unique_name()))
	renders = show({"score": float("nan")}, tasks)

	# MongoDB's queries find NaN with NaN
	tasks.insert({"text": "nan", "score": float("nan"), "n": 1})
	settled()

	assert renders[-1] == ["nan"]


@pytest.mark.mongo
def test_a_collection_with_a_collation_re_renders_on_every_change():

	from pymongo.collation import Collation

	name = unique_name()
	mongo.database().create_collection(name, collation=Collation("en", strength=2))
	tasks = watched(Collection(name))
	renders = show({"text": "ada"}, tasks)

	# Case-insensitive: "Ada" is found by "ada"
	tasks.insert({"text": "Ada", "n": 1})
	settled()

	assert renders[-1] == ["Ada"]


@pytest.mark.mongo
def test_a_shared_component_shown_on_other_pages_stays_up_to_date(monkeypatch):

	import threading
	from domino.testing import TestPage

	tasks = watched(Collection(unique_name()))
	tasks.insert({"text": "a", "done": False})
	tasks.insert({"text": "b", "done": False})
	settled()

	class Board(t.ul):

		def render(self):
			return [t.li() [task["text"], t.button(on_click=self.finish_first) ["Done"]] for task in tasks.find({"done": False}, sort="text")]

		def finish_first(self):
			tasks.update({"done": False}, {"$set": {"done": True}})

	# One instance on every page, like a board everyone sees
	board = Board()
	app = Domino(__name__)
	apps.append(app)

	@app.route("/")
	def index():
		return Document() [board]

	first = TestPage(app)
	second = TestPage(app)

	# The change stream announces the change only after the click's response
	gate = threading.Event()
	announce = mongo.changed_documents

	def later(change):
		gate.wait(1)
		return announce(change)

	monkeypatch.setattr(mongo, "changed_documents", later)
	first.click("button")
	gate.set()
	settled()

	assert first.sync().text().count("Done") == 1
	assert second.sync().text().count("Done") == 1


@pytest.mark.mongo
def test_a_change_too_large_to_send_with_its_document_still_re_renders():

	name = unique_name()
	tasks = watched(Collection(name))
	# Almost MongoDB's 16 MB limit, so the event with the whole document is over it
	big = "x" * (16 * 1024 * 1024 - 200)
	mongo.database()[name].insert_one({"_id": "big", "text": "big", "done": True, "n": 1, "blob": big})
	settled()
	renders = show({"done": False}, tasks, sort=None)

	mongo.database()[name].update_one({"_id": "big"}, {"$set": {"done": False}})
	settled()
	assert tasks.store().watching
	assert renders[-1] == ["big"]

	# Still live afterwards
	mongo.database()[name].insert_one({"_id": "small", "text": "small", "done": False, "n": 2})
	settled()
	assert sorted(renders[-1]) == ["big", "small"]
