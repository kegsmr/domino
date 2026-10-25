import os
import uuid
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
