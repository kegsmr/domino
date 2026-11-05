import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import domino._cli as cli
from domino import Domino
from domino import _devmongo as devmongo


ROOT = Path(__file__).resolve().parent.parent

# A MongoDB server for tests, as conftest.py reads it
TEST_MONGO_URL = os.environ.get("DOMINO_TEST_MONGO_URL")

# A mongod downloaded by an earlier `domino run`, which the plugin can start without downloading
CACHED_MONGOD = devmongo.cached_mongod(devmongo.domino_home() / "mongodb", devmongo.DEFAULT_VERSION)

needs_mongod = pytest.mark.skipif(CACHED_MONGOD is None, reason="needs a downloaded mongod in ~/.domino/mongodb (run `domino run` once)")
needs_test_mongo_url = pytest.mark.skipif(not TEST_MONGO_URL, reason="needs MongoDB: set DOMINO_TEST_MONGO_URL")


def write(folder, files):

	for name, content in files.items():
		path = folder / name
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(textwrap.dedent(content), encoding="utf-8")


def run_pytest(folder, *args, env=None):

	# This checkout's Domino and pytest plugin, and none of the MongoDB settings of the shell
	# (or of conftest.py) unless the test passes them
	environ = {name: value for name, value in os.environ.items() if not name.startswith("DOMINO_") and name != "MONGO_URL"}
	if "DOMINO_HOME" in os.environ:
		environ["DOMINO_HOME"] = os.environ["DOMINO_HOME"]
	environ["PYTHONPATH"] = os.pathsep.join([str(ROOT)] + [path for path in [os.environ.get("PYTHONPATH")] if path])
	environ.update(env or {})

	result = subprocess.run(
		[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args, str(folder)],
		capture_output=True, text=True, cwd=folder, env=environ,
	)

	return result.returncode, result.stdout + result.stderr


COUNTER = """
	import domino.tags as t
	from domino import State


	class Counter(t.div):

		count = State(0)

		def render(self):
			return [t.p() [f"Count: {self.count}"], t.button(on_click=self.increment) ["+"]]

		def increment(self):
			self.count += 1
"""


def make_app(folder):

	write(folder, {
		"components/counter.py": COUNTER,
		"pages/index.py": """
			from components.counter import Counter

			def page():
				return Counter()
		""",
		"pages/blog/index.py": """
			import domino.tags as t

			def page():
				return t.h1() ["Blog"]
		""",
		"pages/blog/[slug].py": """
			import domino.tags as t

			def page(slug):
				return t.h1() [slug.replace("-", " ").title()]
		""",
		# Same file name as pages/index_test.py: they mustn't clash
		"pages/index_test.py": """
			def test_click(page):
				page.click("button")
				assert page.text("p") == "Count: 1"
		""",
		"pages/blog/index_test.py": """
			def test_title(page):
				assert page.text("h1") == "Blog"

			def test_other_paths(open_page):
				assert open_page("/").text("p") == "Count: 0"
		""",
		"pages/blog/[slug]_test.py": """
			def test_slug(open_page):
				assert open_page(slug="hello-world").text("h1") == "Hello World"
		""",
	})


def test_tests_next_to_pages_get_their_page(tmp_path):

	make_app(tmp_path)

	code, output = run_pytest(tmp_path)

	assert code == 0, output
	assert "4 passed" in output


def test_failures_show_pytest_assertion_details(tmp_path):

	make_app(tmp_path)
	write(tmp_path, {"pages/index_test.py": """
		def test_click(page):
			page.click("button")
			assert page.text("p") == "Count: 2"
	"""})

	code, output = run_pytest(tmp_path, "pages/index_test.py")

	assert code == 1
	# Rewritten assert: both sides shown
	assert "'Count: 1' == 'Count: 2'" in output


def test_a_parameter_page_needs_its_parameters(tmp_path):

	make_app(tmp_path)
	write(tmp_path, {"pages/blog/[slug]_test.py": """
		def test_slug(page):
			pass
	"""})

	code, output = run_pytest(tmp_path, "-k", "test_slug")

	assert code != 0
	assert "use open_page(slug=...)" in output


def test_handler_errors_come_with_their_traceback(tmp_path):

	make_app(tmp_path)
	write(tmp_path, {
		"pages/broken.py": """
			import domino.tags as t

			class Broken(t.div):
				def render(self):
					return [t.button(on_click=self.explode) ["Boom"]]

				def explode(self):
					raise ValueError("kaboom")

			def page():
				return Broken()
		""",
		"pages/broken_test.py": """
			def test_boom(page):
				page.click("button")
		""",
	})

	code, output = run_pytest(tmp_path, "pages/broken_test.py")

	assert code == 1
	assert "ValueError: kaboom" in output
	assert 'raise ValueError("kaboom")' in output


def test_test_files_are_not_pages(tmp_path):

	make_app(tmp_path)

	app = Domino("page_tests_app", root_path=str(tmp_path))
	rules = {rule.rule for rule in app.url_map.iter_rules()}

	assert {"/", "/blog", "/blog/<slug>"} <= rules
	assert not any("test" in rule for rule in rules)


# MongoDB for named Collections, like `meteor test`


TASKS = """
	import domino.tags as t

	from data import tasks


	class Tasks(t.div):

		def render(self):
			return [
				t.form(on_submit=self.add) [t.input(name="text"), t.button(type="submit") ["Add"]],
				t.ul()([t.li() [task["text"]] for task in tasks.find(sort="text")]),
			]

		def add(self, event):
			tasks.insert({"text": event.form["text"]})
"""


def make_mongo_app(folder, settings=None):

	write(folder, {
		"data.py": """
			from domino import Collection

			tasks = Collection("tasks")
		""",
		"components/tasks.py": TASKS,
		"pages/index.py": """
			from components.tasks import Tasks

			def page():
				return Tasks()
		""",
		"pages/about.py": """
			import domino.tags as t

			def page():
				return t.h1() ["About"]
		""",
		# Runs first: a page without named Collections doesn't start MongoDB
		"pages/about_test.py": """
			from domino import _pytest_plugin as pytest_plugin

			def test_no_mongodb_yet(page, request):
				assert page.text("h1") == "About"
				server = pytest_plugin._servers.get(request.config)
				assert server is None or server.mongod is None
		""",
		"pages/index_test.py": """
			import json
			from pathlib import Path

			from domino import _pytest_plugin as pytest_plugin


			def test_add(page, open_page, domino_db, request):
				other = open_page()
				page.fill("input[name=text]", "Buy milk")
				page.click("button", text="Add")
				other.sync()
				assert page.text("ul") == "Buy milk"
				assert other.text("ul") == "Buy milk"

				# For the test that runs this session: what was started, and where
				server = pytest_plugin._servers[request.config]
				mongod = server.mongod
				state = {"pid": mongod and mongod.process.pid, "folder": server.folder, "database": domino_db.name}
				Path("mongod.json").write_text(json.dumps(state))


			def test_each_test_starts_empty(page, domino_db):
				assert page.find_all("li") == []
				assert domino_db["tasks"].count_documents({}) == 0
		""",
	})

	if settings is not None:
		write(folder, {"settings.json": settings})


@needs_mongod
def test_named_collections_get_a_mongodb_with_nothing_configured(tmp_path):

	make_mongo_app(tmp_path)

	code, output = run_pytest(tmp_path)

	assert code == 0, output
	assert "3 passed" in output

	state = json.loads((tmp_path / "mongod.json").read_text())
	assert state["pid"]
	# Its own data folder, not the app's .domino/, and nothing left running or behind
	assert not (tmp_path / ".domino").exists()
	assert not Path(state["folder"]).exists()
	assert not devmongo.pid_alive(state["pid"])


@needs_test_mongo_url
def test_domino_test_mongo_url_is_used_without_starting_anything(tmp_path):

	import pymongo

	make_mongo_app(tmp_path)
	write(tmp_path, {"pages/server_test.py": """
		import os

		from domino import _pytest_plugin as pytest_plugin


		def test_uses_the_server(domino_db, request):
			host, port = domino_db.client.address
			assert f":{port}/" in os.environ["DOMINO_TEST_MONGO_URL"]
			assert domino_db.name.startswith("domino_test_")
	"""})

	code, output = run_pytest(tmp_path, env={"DOMINO_TEST_MONGO_URL": TEST_MONGO_URL})

	assert code == 0, output
	assert "4 passed" in output

	state = json.loads((tmp_path / "mongod.json").read_text())
	assert state["pid"] is None and state["folder"] is None

	# Each test's database was dropped
	with pymongo.MongoClient(TEST_MONGO_URL) as client:
		assert state["database"] not in client.list_database_names()


@pytest.mark.parametrize("args, env, settings", [
	(["--no-mongo"], {}, None),
	([], {"DOMINO_NO_MONGO": "1"}, None),
	([], {}, '{"mongo": {"auto": false}}'),
], ids=["option", "environment", "setting"])
def test_turning_it_off_explains_how_to_use_a_server(tmp_path, args, env, settings):

	make_mongo_app(tmp_path, settings)

	code, output = run_pytest(tmp_path, "pages/index_test.py", *args, env=env)

	assert code == 1
	assert "2 errors" in output or "2 failed" in output, output
	assert "MongoNotConfigured" in output
	assert "starting one for tests is turned off" in output
	assert "DOMINO_TEST_MONGO_URL" in output


def test_a_mongod_that_cant_start_explains_how_to_use_a_server(tmp_path):

	make_mongo_app(tmp_path)
	write(tmp_path, {"conftest.py": """
		from domino import _devmongo as devmongo

		calls = []

		def offline(*args, **kwargs):
			calls.append(1)
			assert len(calls) == 1, "tried to download again"
			raise devmongo.DevMongoError("can't reach downloads.mongodb.org")

		devmongo.ensure_mongod = offline
	"""})

	code, output = run_pytest(tmp_path, "pages/index_test.py")

	assert code == 1
	assert "Couldn't start a MongoDB for the tests: can't reach downloads.mongodb.org" in output
	assert "Set DOMINO_TEST_MONGO_URL" in output
	# Both tests fail with it, without trying again
	assert "2 errors" in output or "2 failed" in output, output
	assert "tried to download again" not in output


def test_the_created_app_has_a_passing_page_test(tmp_path):

	if TEST_MONGO_URL:
		env = {"DOMINO_TEST_MONGO_URL": TEST_MONGO_URL}
	elif CACHED_MONGOD is not None:
		env = {}
	else:
		pytest.skip("needs MongoDB: set DOMINO_TEST_MONGO_URL, or run `domino run` once to download mongod")

	cli.create(str(tmp_path / "scaffold"))

	code, output = run_pytest(tmp_path / "scaffold", env=env)

	assert code == 0, output
	assert "2 passed" in output
