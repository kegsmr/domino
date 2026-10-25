import os
import sys
import uuid
from pathlib import Path, PurePosixPath

import pytest

import domino.cli as cli
from domino import Domino, pages
from domino.pages import PagesError


@pytest.fixture(autouse=True)
def forget_app(tmp_path, forget_modules):

	yield

	# Each test's app has its own components/ and data.py
	forget_modules(tmp_path)


def write(folder, files):

	for name, text in files.items():
		path = folder / name
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(text, encoding="utf-8")


def make_app(folder, files, **kwargs):

	write(folder, files)

	return Domino(f"pages_test_{uuid.uuid4().hex[:8]}", root_path=str(folder), **kwargs)


def get(app, url):

	response = app.test_client().get(url)

	return response.status_code, response.get_data(as_text=True)


def text_page(text):

	return f"def page(**params):\n\treturn {text!r}.format(**params)\n"


TEXT_LAYOUT = (
	"def layout(content, **params):\n"
	"\treturn '<{name}>' + str(content) + '</{name}>'\n"
)


# URL rules


@pytest.mark.parametrize("path, rule", [
	("index.py", "/"),
	("about.py", "/about"),
	("users/index.py", "/users"),
	("users/[id].py", "/users/<id>"),
	("users/[int:id].py", "/users/<int:id>"),
	("files/[...rest].py", "/files/<path:rest>"),
	("users/[id]/posts.py", "/users/<id>/posts"),
	("users/[id]/index.py", "/users/<id>"),
	("[lang]/docs/[...page].py", "/<lang>/docs/<path:page>"),
])
def test_url_rules(path, rule):

	assert pages.url_rule(PurePosixPath(path)) == rule


def test_a_bad_parameter_name_is_a_clear_error():

	with pytest.raises(PagesError, match=r"\[user-id\]"):
		pages.url_rule(PurePosixPath("[user-id].py"))


def test_files_become_routes_and_private_files_are_skipped(tmp_path):

	app = make_app(tmp_path, {
		"pages/index.py": text_page("home"),
		"pages/about.py": text_page("about"),
		"pages/users/index.py": text_page("users"),
		"pages/users/[int:id].py": text_page("user {id}"),
		"pages/users/[id]/posts.py": text_page("posts of {id}"),
		"pages/files/[...rest].py": text_page("file {rest}"),
		"pages/_helpers.py": "raise RuntimeError('a private helper is not a page')\n",
		"pages/_drafts/secret.py": text_page("secret"),
	})

	rules = {rule.rule for rule in app.url_map.iter_rules() if rule.endpoint.startswith("pages/")}

	assert rules == {"/", "/about", "/users", "/users/<int:id>", "/users/<id>/posts", "/files/<path:rest>"}
	assert get(app, "/") == (200, "home")
	assert get(app, "/about") == (200, "about")
	assert get(app, "/users") == (200, "users")
	assert get(app, "/users/7") == (200, "user 7")
	assert get(app, "/users/ada/posts") == (200, "posts of ada")
	assert get(app, "/files/a/b.txt") == (200, "file a/b.txt")
	assert get(app, "/_drafts/secret")[0] == 404


def test_url_parameters_arrive_as_keyword_arguments(tmp_path):

	app = make_app(tmp_path, {
		"pages/users/[int:id].py": "def page(id):\n\treturn f'{type(id).__name__} {id}'\n",
	})

	assert get(app, "/users/42") == (200, "int 42")
	assert get(app, "/users/ada")[0] == 404


def test_two_files_for_one_url_are_an_error(tmp_path):

	with pytest.raises(PagesError, match='Two pages for "/about": about/index.py and about.py'):
		make_app(tmp_path, {
			"pages/about.py": text_page("a"),
			"pages/about/index.py": text_page("b"),
		})


def test_a_file_without_page_is_an_error(tmp_path):

	with pytest.raises(PagesError, match="empty.py has no page"):
		make_app(tmp_path / "one", {"pages/empty.py": "x = 1\n"})

	# domino's own Page (the event registry) isn't a page component
	with pytest.raises(PagesError, match="star.py has no page"):
		make_app(tmp_path / "two", {"pages/star.py": "from domino import *\n"})


# Page components


def test_page_class_gets_url_parameters_in_init(tmp_path):

	app = make_app(tmp_path, {
		"pages/users/[id].py": (
			"import domino.tags as t\n"
			"class Page(t.div):\n"
			"\tdef init(self, id):\n"
			"\t\tself.user = id\n"
			"\tdef render(self):\n"
			"\t\treturn [t.h1() [f'User {self.user}']]\n"
		),
		"pages/index.py": "import domino.tags as t\nclass Page(t.p):\n\tdef render(self):\n\t\treturn ['home']\n",
	})

	status, html = get(app, "/users/ada")

	assert status == 200
	assert 'class="Page"' in html and "User ada" in html
	assert "home" in get(app, "/")[1]


def test_page_class_without_init_for_parameters_is_an_error(tmp_path):

	with pytest.raises(PagesError, match=r"add init\(self, id\)"):
		make_app(tmp_path, {"pages/[id].py": "import domino.tags as t\nclass Page(t.div):\n\tpass\n"})


def test_a_component_without_layout_gets_a_document(tmp_path):

	app = make_app(tmp_path, {"pages/index.py": "import domino.tags as t\ndef page():\n\treturn t.p() ['hi']\n"})

	html = get(app, "/")[1]

	# Domino's script and the page id, which events need
	assert html.startswith("<!DOCTYPE html>")
	assert 'src="/_domino/core"' in html
	assert "data-domino-page=" in html


# Layouts


def test_layouts_nest_from_the_pages_folder_inward(tmp_path):

	app = make_app(tmp_path, {
		"pages/layout.py": TEXT_LAYOUT.format(name="root"),
		"pages/users/layout.py": TEXT_LAYOUT.format(name="users"),
		"pages/users/[id]/layout.py": TEXT_LAYOUT.format(name="user"),
		"pages/users/[id]/posts.py": text_page("posts of {id}"),
		"pages/users/index.py": text_page("users"),
		"pages/about.py": text_page("about"),
	})

	assert get(app, "/users/ada/posts") == (200, "<root><users><user>posts of ada</user></users></root>")
	assert get(app, "/users") == (200, "<root><users>users</users></root>")
	assert get(app, "/about") == (200, "<root>about</root>")


def test_layouts_get_the_url_parameters_they_ask_for(tmp_path):

	app = make_app(tmp_path, {
		"pages/layout.py": "def layout(content):\n\treturn 'root:' + content\n",
		"pages/[name]/layout.py": "def layout(content, name):\n\treturn f'{name}:' + content\n",
		"pages/[name]/index.py": text_page("hi"),
	})

	assert get(app, "/ada") == (200, "root:ada:hi")


def test_a_page_returning_a_document_skips_layouts(tmp_path):

	app = make_app(tmp_path, {
		"pages/layout.py": (
			"import domino.tags as t\n"
			"from domino.components import Document\n"
			"def layout(content):\n"
			"\treturn Document(title='Site') [t.nav() ['NAV'], content]\n"
		),
		"pages/index.py": "import domino.tags as t\ndef page():\n\treturn t.p() ['inside']\n",
		"pages/print.py": (
			"import domino.tags as t\n"
			"from domino.components import Document\n"
			"def page():\n"
			"\treturn Document(title='Print') [t.p() ['alone']]\n"
		),
	})

	inside = get(app, "/")[1]
	alone = get(app, "/print")[1]

	assert "NAV" in inside and "inside" in inside
	assert inside.index("NAV") < inside.index("inside")
	assert "NAV" not in alone and "alone" in alone


def test_flask_responses_skip_layouts(tmp_path):

	app = make_app(tmp_path, {
		"pages/layout.py": TEXT_LAYOUT.format(name="root"),
		"pages/feed.py": "from flask import jsonify\ndef page():\n\treturn jsonify(ok=True)\n",
	})

	response = app.test_client().get("/feed")

	assert response.get_json() == {"ok": True}


# 404


def test_404_page_has_status_404_and_its_layout(tmp_path):

	app = make_app(tmp_path, {
		"pages/layout.py": TEXT_LAYOUT.format(name="root"),
		"pages/404.py": text_page("not found"),
		"pages/index.py": text_page("home"),
		"pages/gone.py": "from flask import abort\ndef page():\n\tabort(404)\n",
	})

	assert get(app, "/nowhere") == (404, "<root>not found</root>")
	assert get(app, "/gone") == (404, "<root>not found</root>")
	assert "404" not in {rule.rule for rule in app.url_map.iter_rules()}


def test_404_page_only_in_the_pages_folder(tmp_path):

	with pytest.raises(PagesError, match="404.py only works in the pages folder"):
		make_app(tmp_path, {"pages/users/404.py": text_page("x")})


# Explicit routes


def test_explicit_routes_still_work_alongside_pages(tmp_path):

	app = make_app(tmp_path, {"pages/index.py": text_page("home")})

	@app.route("/api")
	def api():
		return "api"

	assert get(app, "/") == (200, "home")
	assert get(app, "/api") == (200, "api")


def test_an_explicit_route_for_a_page_url_is_an_error(tmp_path):

	app = make_app(tmp_path, {"pages/about.py": text_page("about")})

	with pytest.raises(PagesError, match='Two handlers for "/about": about.py and the route "about_page"'):
		@app.route("/about")
		def about_page():
			return "explicit"


def test_a_page_for_an_existing_route_is_an_error(tmp_path):

	# Flask's own /static/<path:filename> route exists before pages are added
	with pytest.raises(PagesError, match='Two handlers for "/static/<path:filename>"'):
		make_app(tmp_path, {"pages/static/[...filename].py": text_page("x")})


# Options


def test_pages_false_turns_pages_off(tmp_path):

	app = make_app(tmp_path, {"pages/index.py": text_page("home")}, pages=False)

	assert get(app, "/")[0] == 404


def test_pages_can_live_in_another_folder(tmp_path):

	app = make_app(tmp_path, {"views/index.py": text_page("from views"), "pages/index.py": text_page("ignored")}, pages="views")

	assert get(app, "/") == (200, "from views")


def test_a_missing_pages_folder_is_an_error_only_when_named(tmp_path):

	assert get(make_app(tmp_path / "plain", {}), "/")[0] == 404

	with pytest.raises(PagesError, match="No pages folder"):
		make_app(tmp_path / "named", {}, pages="views")


def test_pages_are_found_once_not_per_request(tmp_path, monkeypatch):

	loaded = []
	load_module = pages.load_module
	monkeypatch.setattr(pages, "load_module", lambda path, name: loaded.append(name) or load_module(path, name))

	app = make_app(tmp_path, {
		"pages/layout.py": TEXT_LAYOUT.format(name="root"),
		"pages/index.py": text_page("home"),
		"pages/[name].py": text_page("hi {name}"),
	})
	for url in ["/", "/ada", "/grace", "/"]:
		assert get(app, url)[0] == 200

	assert sorted(name.rsplit(".", 1)[-1] for name in loaded) == ["[name]", "index", "layout"]


# Imports


def test_pages_import_from_the_app_folder_from_any_working_directory(tmp_path, monkeypatch):

	elsewhere = tmp_path / "elsewhere"
	elsewhere.mkdir()
	monkeypatch.chdir(elsewhere)
	monkeypatch.setattr(sys, "path", [path for path in sys.path if path not in ("", ".")])

	app = make_app(tmp_path / "app", {
		"components/greeting.py": "def greeting(name):\n\treturn f'Hello, {name}!'\n",
		"data.py": "NAME = 'Ada'\n",
		"pages/index.py": (
			"from components.greeting import greeting\n"
			"from data import NAME\n"
			"def page():\n"
			"\treturn greeting(NAME)\n"
		),
	})

	assert get(app, "/") == (200, "Hello, Ada!")


def test_page_modules_have_unique_names_in_sys_modules(tmp_path):

	first = make_app(tmp_path / "one", {"pages/users/[id].py": text_page("one {id}")})
	second = make_app(tmp_path / "two", {"pages/users/[id].py": text_page("two {id}")})

	# In sys.modules, so the reloader restarts the server when a page changes
	module = sys.modules[f"domino_pages.{first.import_name}.users.[id]"]

	assert Path(module.__file__) == tmp_path / "one" / "pages" / "users" / "[id].py"
	assert get(first, "/users/1") == (200, "one 1")
	assert get(second, "/users/1") == (200, "two 1")


# Events


def test_events_and_state_work_on_a_page(tmp_path):

	app = make_app(tmp_path, {
		"pages/layout.py": (
			"import domino.tags as t\n"
			"from domino.components import Document\n"
			"def layout(content):\n"
			"\treturn Document() [t.nav() ['NAV'], content]\n"
		),
		"pages/index.py": (
			"import domino.tags as t\n"
			"from domino import State\n"
			"class Page(t.div):\n"
			"\tcount = State(0)\n"
			"\tdef render(self):\n"
			"\t\treturn [t.p() [f'Count: {self.count}'], t.button(on_click=self.increment) ['+']]\n"
			"\tdef increment(self):\n"
			"\t\tself.count += 1\n"
		),
	})
	client = app.test_client()

	html = client.get("/").get_data(as_text=True)
	page_id = html.split('data-domino-page="')[1].split('"')[0]
	event_id = html.split('data-event-id="')[1].split('"')[0]
	response = client.post("/_domino/events", json={"page_id": page_id, "event_id": event_id})

	assert "NAV" in html and "Count: 0" in html
	assert response.status_code == 200
	assert "Count: 1" in response.get_json()["html"]


# domino run <folder>


@pytest.fixture
def served(monkeypatch):
	"""Records the apps `domino run` would serve, instead of serving them."""

	apps = []
	# Domino.run() serves through domino.asgi.serve (uvicorn)
	monkeypatch.setattr("domino.asgi.serve", lambda app, *args, **kwargs: apps.append(app))

	# --no-mongo sets this; set then deleted so it's removed again after the test
	monkeypatch.setenv("DOMINO_NO_MONGO", "")
	monkeypatch.delenv("DOMINO_NO_MONGO")

	return apps


def test_domino_run_makes_an_app_for_a_folder_with_only_pages(tmp_path, served):

	write(tmp_path / "site", {"pages/index.py": text_page("zero boilerplate"), "settings.json": '{"name": "site"}'})

	assert cli.main(["run", str(tmp_path / "site"), "--no-mongo"]) == 0

	app, = served
	assert Path(app.root_path) == tmp_path / "site"
	assert app.settings.name == "site"
	assert get(app, "/") == (200, "zero boilerplate")


def test_domino_run_uses_a_folders_app_py(tmp_path, served):

	write(tmp_path / "site", {
		"app.py": "from domino import Domino\n\napp = Domino(__name__)\napp.custom = True\n",
		"pages/index.py": text_page("home"),
	})

	cli.main(["run", str(tmp_path / "site"), "--no-mongo"])

	app, = served
	assert app.custom is True
	assert get(app, "/") == (200, "home")


def test_domino_run_defaults_to_the_current_folder(tmp_path, served, monkeypatch):

	write(tmp_path / "here", {"pages/index.py": text_page("here")})
	monkeypatch.chdir(tmp_path / "here")

	cli.main(["run", "--no-mongo"])

	assert get(served[0], "/") == (200, "here")


def test_domino_run_a_folder_without_an_app_is_a_clear_error(tmp_path, served, capsys):

	(tmp_path / "empty").mkdir()

	assert cli.main(["run", str(tmp_path / "empty"), "--no-mongo"]) == 1
	assert "No app.py or pages/ folder" in capsys.readouterr().err
	assert served == []


# domino create (rendering it needs MongoDB: see test_cli.py's test_created_app_renders)


def test_domino_create_makes_a_pages_app(tmp_path):

	cli.create(str(tmp_path / "new"))

	app = make_app(tmp_path / "new", {})

	assert "/" in {rule.rule for rule in app.url_map.iter_rules()}
	assert "layout(content)" in (tmp_path / "new" / "pages" / "layout.py").read_text()
	assert "from data import tasks" in (tmp_path / "new" / "components" / "tasks.py").read_text()
	assert len((tmp_path / "new" / "app.py").read_text().splitlines()) < 12
	assert os.path.exists(tmp_path / "new" / "data.py")
