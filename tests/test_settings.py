import json
import os

import pytest

import domino.tags as t
from domino import Domino
from domino.components import Document, PublicSettings
from domino.settings import SettingsError


@pytest.fixture(autouse=True)
def clean_environ(monkeypatch):

	# DOMINO_* variables from the shell running the tests would leak into every app
	for name in list(os.environ):
		if name.startswith("DOMINO_"):
			monkeypatch.delenv(name)


def write(path, data):

	path.write_text(json.dumps(data), encoding="utf-8")


def make_app(tmp_path):

	return Domino(__name__, root_path=str(tmp_path))


def render_home(app, page):

	app.route("/")(page)

	return app.test_client().get("/").get_data(as_text=True)


def test_no_files_means_empty_settings(tmp_path):

	assert make_app(tmp_path).settings == {}


def test_settings_json_is_read_from_the_root_path(tmp_path):

	write(tmp_path / "settings.json", {"site_name": "Demo", "mongo": {"url": "mongodb://db"}})

	assert make_app(tmp_path).settings == {"site_name": "Demo", "mongo": {"url": "mongodb://db"}}


def test_local_file_deep_merges_over_settings_json(tmp_path):

	write(tmp_path / "settings.json", {"mongo": {"url": "mongodb://db", "pool": 5}, "tags": [1, 2], "debug": False})
	write(tmp_path / "settings.local.json", {"mongo": {"url": "mongodb://localhost"}, "tags": [3], "debug": True})

	assert make_app(tmp_path).settings == {
		"mongo": {"url": "mongodb://localhost", "pool": 5},
		"tags": [3],
		"debug": True
	}


def test_environment_overrides_files(tmp_path, monkeypatch):

	write(tmp_path / "settings.json", {"mongo": {"url": "mongodb://db", "pool": 5}, "name": "Demo"})
	write(tmp_path / "settings.local.json", {"name": "Local"})
	monkeypatch.setenv("DOMINO_MONGO__URL", "mongodb://env")
	monkeypatch.setenv("DOMINO_NAME", "Env")
	monkeypatch.setenv("DOMINO_PORT", "8080")
	monkeypatch.setenv("DOMINO_DEBUG", "true")
	monkeypatch.setenv("DOMINO_NOTHING", "null")
	monkeypatch.setenv("DOMINO_FEATURES", '["a", "b"]')
	monkeypatch.setenv("DOMINO_CACHE", '{"size": 10}')

	settings = make_app(tmp_path).settings

	assert settings["mongo"] == {"url": "mongodb://env", "pool": 5}
	assert settings["name"] == "Env"
	assert settings["port"] == 8080
	assert settings["debug"] is True
	assert settings["nothing"] is None
	assert settings["features"] == ["a", "b"]
	assert settings["cache"] == {"size": 10}


def test_environment_values_that_arent_json_stay_strings(tmp_path, monkeypatch):

	monkeypatch.setenv("DOMINO_GREETING", "hello world")
	monkeypatch.setenv("DOMINO_VERSION", "1.2.3")

	settings = make_app(tmp_path).settings

	assert settings["greeting"] == "hello world"
	assert settings["version"] == "1.2.3"


def test_domino_settings_variable_points_at_another_file(tmp_path, monkeypatch):

	write(tmp_path / "settings.json", {"name": "default"})
	other = tmp_path / "config" / "production.json"
	other.parent.mkdir()
	write(other, {"name": "production", "mongo": {"url": "a"}})
	write(tmp_path / "config" / "production.local.json", {"mongo": {"url": "b"}})
	monkeypatch.setenv("DOMINO_SETTINGS", str(other))

	settings = make_app(tmp_path).settings

	# The variable chooses the file; it isn't a setting itself
	assert settings == {"name": "production", "mongo": {"url": "b"}}


def test_settings_argument_chooses_the_file(tmp_path):

	(tmp_path / "config").mkdir()
	write(tmp_path / "config" / "app.json", {"name": "from argument"})

	app = Domino(__name__, root_path=str(tmp_path), settings="config/app.json")

	assert app.settings == {"name": "from argument"}


def test_invalid_json_names_the_file_and_line(tmp_path):

	(tmp_path / "settings.json").write_text('{\n  "name": "Demo",\n  oops\n}', encoding="utf-8")

	with pytest.raises(SettingsError) as error:
		make_app(tmp_path)

	assert "settings.json" in str(error.value)
	assert "line 3" in str(error.value)


def test_domino_block_feeds_flask_config(tmp_path):

	write(tmp_path / "settings.json", {"domino": {"page_ttl": 600, "max_pages": 500, "keepalive": 5}})

	app = make_app(tmp_path)

	assert app.config["DOMINO_PAGE_TTL"] == 600
	assert app.config["DOMINO_MAX_PAGES"] == 500
	assert app.config["DOMINO_KEEPALIVE"] == 5


def test_config_defaults_without_a_domino_block(tmp_path):

	app = make_app(tmp_path)

	assert app.config["DOMINO_PAGE_TTL"] == 30 * 60
	assert app.config["DOMINO_MAX_PAGES"] == 1000


def test_secret_key_setting(tmp_path, monkeypatch):

	assert make_app(tmp_path).secret_key is None

	monkeypatch.setenv("DOMINO_SECRET_KEY", "s3cret")

	assert make_app(tmp_path).secret_key == "s3cret"


def test_public_settings_are_emitted_into_document_head(tmp_path):

	write(tmp_path / "settings.json", {"public": {"greeting": "Hi"}})
	app = make_app(tmp_path)

	html = render_home(app, lambda: Document(title="Home"))

	head = html.split("</head>")[0]
	assert 'type="application/json" id="domino-settings">' in head
	assert '{"greeting": "Hi"}' in head
	# Before core.js, which reads it when it loads
	assert head.index("domino-settings") < head.index("/_domino/core")


def test_public_settings_cant_break_out_of_the_script(tmp_path):

	write(tmp_path / "settings.json", {"public": {"evil": "</script><script>alert(1)</script><!-- & more"}})
	app = make_app(tmp_path)

	html = render_home(app, lambda: Document())

	assert "alert(1)" in html
	assert "</script><script>alert(1)" not in html
	assert "<!--" not in html
	start = html.index('id="domino-settings">') + len('id="domino-settings">')
	data = html[start:html.index("</script>", start)]
	assert json.loads(data) == {"evil": "</script><script>alert(1)</script><!-- & more"}


def test_non_public_settings_never_appear_in_html(tmp_path):

	write(tmp_path / "settings.json", {
		"secret_key": "top-secret-key",
		"mongo": {"url": "mongodb://user:hunter2@db"},
		"public": {"greeting": "Hi"}
	})
	app = make_app(tmp_path)

	html = render_home(app, lambda: Document())

	assert "top-secret-key" not in html
	assert "hunter2" not in html
	assert "Hi" in html


def test_no_settings_tag_without_public_settings(tmp_path):

	write(tmp_path / "settings.json", {"secret_key": "x", "public": {}})
	app = make_app(tmp_path)

	assert "domino-settings" not in render_home(app, lambda: Document())


def test_public_settings_component_for_custom_pages(tmp_path):

	write(tmp_path / "settings.json", {"public": {"theme": "dark"}})
	app = make_app(tmp_path)

	html = render_home(app, lambda: t.html() [t.head() [PublicSettings()], t.body()])

	assert 'type="application/json" id="domino-settings">' in html
	assert '{"theme": "dark"}' in html


def test_attribute_access(tmp_path):

	write(tmp_path / "settings.json", {"mongo": {"url": "mongodb://db"}, "servers": [{"host": "a"}]})
	settings = make_app(tmp_path).settings

	assert settings.mongo.url == "mongodb://db"
	assert settings["mongo"]["url"] == "mongodb://db"
	assert settings.servers[0].host == "a"
	assert settings.get("missing") is None
	assert settings.get("missing", 1) == 1
	assert isinstance(settings, dict)

	with pytest.raises(AttributeError, match="No setting 'missing'.*mongo"):
		settings.missing


def test_latency_setting_only_applies_while_debugging():

	import domino.tags as t
	from domino import Domino
	from domino.components import Document

	app = Domino(__name__)
	app.config["DOMINO_LATENCY"] = 300

	class Box(t.div):

		def render(self):
			return [t.button(on_click=lambda: None) ["x"]]

	@app.route("/")
	def index():
		return Document() [Box()]

	assert "data-domino-latency" not in app.test_client().get("/").get_data(as_text=True)

	app.debug = True
	assert 'data-domino-latency="300"' in app.test_client().get("/").get_data(as_text=True)
