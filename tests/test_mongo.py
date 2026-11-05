import time
import uuid

import pytest

import domino.tags as t
from domino import Collection, Domino, mongo
from domino import Document


def unique_name():

	return f"test_{uuid.uuid4().hex[:8]}"


def wait_for(condition, timeout=5):

	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		if condition():
			return True
		time.sleep(0.02)

	return False


def subscribed_page(collection, renders):

	class Items(t.div):

		def render(self):
			renders.append(1)
			self([t.li() [document["text"]] for document in collection.find(sort="n")])

	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document() [Items()]

	html = app.test_client().get("/").get_data(as_text=True)
	page_id = html.split('data-domino-page="')[1].split('"')[0]

	return app.page_store.pages[page_id]


@pytest.mark.mongo
def test_crud_and_queries_match_the_in_memory_collection():

	people = Collection(unique_name())
	ada = people.insert({"name": "Ada", "age": 36, "tags": ["math"]})
	people.insert({"name": "Alan", "age": 41, "tags": ["math", "crypto"]})
	people.insert({"name": "Grace", "age": 85, "address": {"city": "NYC"}})

	assert isinstance(ada, str)
	assert people.find_one({"_id": ada})["name"] == "Ada"
	assert [p["name"] for p in people.find({"age": {"$gt": 40}}, sort="age")] == ["Alan", "Grace"]
	assert [p["name"] for p in people.find(sort=[("age", -1)], limit=2)] == ["Grace", "Alan"]
	assert people.count({"tags": "crypto"}) == 1
	assert people.count({"address.city": "NYC"}) == 1
	assert people.count({"$or": [{"name": "Ada"}, {"name": "Grace"}]}) == 2

	assert people.update({"name": "Ada"}, {"$inc": {"age": 1}, "$push": {"tags": "code"}}) == 1
	assert people.find_one({"name": "Ada"})["age"] == 37
	assert people.update({"tags": "math"}, {"$set": {"field": "cs"}}, multi=True) == 2
	assert people.update({"name": "Grace"}, {"name": "Grace Hopper"}) == 1
	assert people.find_one({"name": "Grace Hopper"})["_id"]

	assert people.remove({"field": "cs"}) == 2
	assert people.count() == 1


@pytest.mark.mongo
def test_documents_are_copies_and_reads_see_own_writes_immediately():

	notes = Collection(unique_name())
	notes.insert({"text": "hi", "tags": []})

	note = notes.find_one()
	note["tags"].append("changed")
	assert notes.find_one()["tags"] == []

	notes.insert({"text": "second"})
	assert notes.count() == 2


@pytest.mark.mongo
def test_writes_from_another_process_update_pages():

	name = unique_name()
	items = Collection(name)
	renders = []
	page = subscribed_page(items, renders)
	assert items.store().watching

	# Written straight to MongoDB, like another server process or a script would
	mongo.database()[name].insert_one({"_id": "outside", "text": "from elsewhere", "n": 1})

	assert wait_for(lambda: any("from elsewhere" in update["html"] for update in page.updates.values()))


@pytest.mark.mongo
def test_own_write_renders_subscribers_once():

	items = Collection(unique_name())
	renders = []
	subscribed_page(items, renders)
	renders.clear()

	items.insert({"text": "one", "n": 1})

	assert wait_for(lambda: len(renders) >= 1)
	time.sleep(0.3)
	assert len(renders) == 1


def test_named_collection_without_mongodb_explains_what_to_do(monkeypatch):

	monkeypatch.delenv("DOMINO_MONGO__URL", raising=False)
	monkeypatch.delenv("MONGO_URL", raising=False)
	monkeypatch.setattr(mongo, "_app", None)
	mongo.connect(None)

	try:
		with pytest.raises(mongo.MongoNotConfigured, match="domino run"):
			Collection(unique_name()).insert({"a": 1})
	finally:
		mongo.connect(None)


def test_unnamed_collection_stays_in_memory(monkeypatch):

	monkeypatch.delenv("DOMINO_MONGO__URL", raising=False)
	monkeypatch.setattr(mongo, "_app", None)
	mongo.connect(None)

	local = Collection()
	local.insert({"a": 1})

	assert local.count() == 1
	mongo.connect(None)


@pytest.mark.mongo
def test_pages_stay_live_after_the_collection_is_dropped_and_recreated():

	name = unique_name()
	items = Collection(name)
	renders = []
	page = subscribed_page(items, renders)

	mongo.database().drop_collection(name)
	time.sleep(0.3)
	page.updates.clear()
	mongo.database()[name].insert_one({"_id": "again", "text": "recreated", "n": 1})

	assert wait_for(lambda: any("recreated" in update["html"] for update in page.updates.values()))


@pytest.mark.mongo
def test_raw_collection_is_the_pymongo_collection_and_its_writes_update_pages():

	name = unique_name()
	items = Collection(name)
	renders = []
	page = subscribed_page(items, renders)

	raw = items.raw_collection()
	assert raw.name == name and raw.database == items.raw_database() == mongo.database()

	# What Collection doesn't do: indexes and aggregation
	raw.create_index("n")
	items.insert({"text": "a", "n": 1})
	items.insert({"text": "b", "n": 2})
	assert list(raw.aggregate([{"$group": {"_id": None, "total": {"$sum": "$n"}}}]))[0]["total"] == 3

	# A write through it still reaches open pages
	raw.insert_one({"_id": "raw", "text": "written raw", "n": 3})
	assert wait_for(lambda: any("written raw" in update["html"] for update in page.updates.values()))


def test_an_unnamed_collection_has_no_raw_collection():

	with pytest.raises(TypeError, match="lives in memory"):
		Collection().raw_collection()
