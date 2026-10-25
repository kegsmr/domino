import hashlib
import io
import json
import os
import sys
from pathlib import Path

import pytest

# Imported by module path: `from domino import cli` finds flask.cli, which core's
# `from flask import *` brings into the package namespace
import domino.asgi
import domino.cli as cli
from domino import Domino, devmongo


# The test database conftest.py sets up, read before clean_environ removes it
TEST_MONGO_URL = os.environ.get("DOMINO_MONGO__URL")

# Set by run() and the CLI; set then deleted here so they're removed again after each test
SET_BY_RUN = ["DOMINO_MONGO__URL", "DOMINO_MONGO__VERSION", "DOMINO_NO_MONGO", "DOMINO_ASGI_APP", "FLASK_DEBUG"]


@pytest.fixture(autouse=True)
def clean_environ(monkeypatch):

	# DOMINO_* and Flask variables from the shell running the tests would change what run() does
	for name in list(os.environ):
		if name.startswith("DOMINO_") or name in ("FLASK_DEBUG", "WERKZEUG_RUN_MAIN", "FLASK_RUN_FROM_CLI"):
			monkeypatch.delenv(name)

	for name in SET_BY_RUN:
		monkeypatch.setenv(name, "")
		monkeypatch.delenv(name)


@pytest.fixture
def started(monkeypatch):
	"""Replaces the MongoDB starter and the server (uvicorn) with recorders."""

	calls = {"mongo": [], "run": []}

	def fake_start(app_folder, port=None, major=devmongo.DEFAULT_VERSION):

		calls["mongo"].append((str(app_folder), port, major))
		return devmongo.mongo_url(port or 27017, devmongo.database_name(app_folder))

	def fake_serve(app, host, port, reload, **options):

		calls["run"].append(dict(host=host, port=port, reload=reload, debug=app.debug, **options))

	monkeypatch.setattr(devmongo, "start", fake_start)
	monkeypatch.setattr(domino.asgi, "serve", fake_serve)

	return calls


def write_app(folder, settings=None, name="app.py"):

	folder.mkdir(parents=True, exist_ok=True)
	(folder / name).write_text("from domino import Domino\n\napp = Domino(__name__)\n", encoding="utf-8")

	if settings is not None:
		(folder / "settings.json").write_text(json.dumps(settings), encoding="utf-8")

	return folder / name


def make_app(folder, settings=None):

	folder.mkdir(parents=True, exist_ok=True)
	if settings is not None:
		(folder / "settings.json").write_text(json.dumps(settings), encoding="utf-8")

	return Domino(__name__, root_path=str(folder))


# Arguments


def test_run_arguments_have_meteor_like_defaults():

	args = cli.build_parser().parse_args(["run"])

	assert (args.command, args.app, args.port, args.host, args.no_mongo, args.mongo_version) == ("run", ".", 5000, "127.0.0.1", False, None)


def test_run_arguments_can_be_set():

	args = cli.build_parser().parse_args(["run", "site/main.py", "--port", "8000", "--host", "0.0.0.0", "--no-mongo", "--mongo-version", "8.0"])

	assert (args.app, args.port, args.host, args.no_mongo, args.mongo_version) == ("site/main.py", 8000, "0.0.0.0", True, "8.0")


def test_serve_arguments_default_to_every_core():

	args = cli.build_parser().parse_args(["serve"])

	assert (args.command, args.app, args.workers, args.port, args.host) == ("serve", ".", None, 8000, "127.0.0.1")


def test_serve_arguments_can_be_set():

	args = cli.build_parser().parse_args(["serve", "site", "--workers", "4", "--port", "80", "--host", "0.0.0.0"])

	assert (args.app, args.workers, args.port, args.host) == ("site", 4, 80, "0.0.0.0")


@pytest.mark.parametrize("workers", ["0", "-2", "many"])
def test_serve_needs_at_least_one_worker(workers, capsys):

	with pytest.raises(SystemExit) as exit:
		cli.main(["serve", "--workers", workers])

	assert exit.value.code == 2
	assert "--workers" in capsys.readouterr().err


def test_version_flag(capsys):

	with pytest.raises(SystemExit) as exit:
		cli.main(["--version"])

	assert exit.value.code == 0
	assert capsys.readouterr().out.startswith("domino ")


def test_no_command_prints_help(capsys):

	assert cli.main([]) == 2
	assert "run" in capsys.readouterr().out


# Finding the app


def test_app_is_loaded_from_its_path_with_its_folder_as_root(tmp_path):

	path = write_app(tmp_path / "myapp", {"site_name": "Mine"})

	app = cli.find_app(cli.load_module(path))

	assert isinstance(app, Domino)
	assert Path(app.root_path) == path.parent.resolve()
	assert app.settings.site_name == "Mine"


def test_app_attribute_is_preferred(tmp_path):

	path = tmp_path / "two.py"
	path.write_text("from domino import Domino\n\nother = Domino('other')\napp = Domino(__name__)\n", encoding="utf-8")

	module = cli.load_module(path)

	assert cli.find_app(module) is module.app


def test_any_domino_attribute_is_found(tmp_path):

	path = tmp_path / "site.py"
	path.write_text("from domino import Domino\n\nserver = Domino(__name__)\n", encoding="utf-8")

	module = cli.load_module(path)

	assert cli.find_app(module) is module.server


def test_missing_app_file_is_a_clear_error(tmp_path, capsys):

	assert cli.main(["run", str(tmp_path / "nope.py")]) == 1
	assert "No app at" in capsys.readouterr().err


def test_module_without_an_app_is_a_clear_error(tmp_path):

	path = tmp_path / "empty.py"
	path.write_text("x = 1\n", encoding="utf-8")

	with pytest.raises(cli.CliError, match="No Domino app"):
		cli.find_app(cli.load_module(path))


# domino create


def test_create_scaffolds_an_app(tmp_path, capsys):

	folder = tmp_path / "hello"

	assert cli.main(["create", str(folder)]) == 0

	files = sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file())
	assert files == [".gitignore", "app.py", "components/tasks.py", "data.py", "pages/index.py", "pages/index_test.py", "pages/layout.py", "settings.json"]
	assert json.loads((folder / "settings.json").read_text())["public"]["title"] == "hello"
	assert ".domino/" in (folder / ".gitignore").read_text()
	assert "settings.local.json" in (folder / ".gitignore").read_text()
	assert "domino run" in capsys.readouterr().out


@pytest.mark.mongo
def test_created_app_renders(tmp_path, monkeypatch, forget_modules):

	monkeypatch.setattr(devmongo, "start", None)
	monkeypatch.setenv("DOMINO_MONGO__URL", TEST_MONGO_URL)
	cli.create(str(tmp_path / "rendered"))

	try:
		app = cli.find_app(cli.load_module(tmp_path / "rendered" / "app.py"))
		client = app.test_client()
		response = client.get("/")
		html = response.get_data(as_text=True)

		assert response.status_code == 200
		assert "<h1>" in html and "rendered" in html

		# The page's form adds a task to the collection, and the list shows it
		page_id = html.split('data-domino-page="')[1].split('"')[0]
		event_id = html.split('data-event-id="')[1].split('"')[0]
		data = {"form": {"text": "Write tests"}}
		result = client.post("/_domino/events", json={"page_id": page_id, "event_id": event_id, "data": data}).get_json()

		assert "Write tests" in result["html"]
	finally:
		# Its components/ and data.py would shadow the next app's
		forget_modules(tmp_path / "rendered")


def test_create_refuses_a_non_empty_folder(tmp_path, capsys):

	folder = tmp_path / "taken"
	folder.mkdir()
	(folder / "app.py").write_text("mine", encoding="utf-8")

	assert cli.main(["create", str(folder)]) == 1
	assert (folder / "app.py").read_text() == "mine"
	assert "isn't empty" in capsys.readouterr().err


def test_create_accepts_an_empty_folder(tmp_path):

	(tmp_path / "empty").mkdir()

	assert cli.main(["create", str(tmp_path / "empty")]) == 0


# domino run and Domino.run()


def test_run_starts_mongo_and_exports_the_url(tmp_path, started):

	path = write_app(tmp_path / "my app!")

	assert cli.main(["run", str(path), "--port", "5100"]) == 0

	assert started["mongo"] == [(str(path.parent.resolve()), 5101, "7.0")]
	assert os.environ["DOMINO_MONGO__URL"] == "mongodb://127.0.0.1:5101/myapp?replicaSet=rs0&directConnection=true"
	assert started["run"] == [{"host": "127.0.0.1", "port": 5100, "reload": True, "debug": True}]


def test_run_passes_the_mongo_version(tmp_path, started):

	path = write_app(tmp_path / "versioned")

	cli.main(["run", str(path), "--mongo-version", "8.0"])

	assert started["mongo"][0][2] == "8.0"


def test_run_leaves_mongo_alone_when_settings_have_a_url(tmp_path, started):

	path = write_app(tmp_path / "configured", {"mongo": {"url": "mongodb://db.example/app"}})

	cli.main(["run", str(path)])

	assert started["mongo"] == []
	assert "DOMINO_MONGO__URL" not in os.environ
	assert len(started["run"]) == 1


def test_run_no_mongo_flag(tmp_path, started):

	path = write_app(tmp_path / "plain")

	cli.main(["run", str(path), "--no-mongo"])

	assert started["mongo"] == []
	assert "DOMINO_MONGO__URL" not in os.environ


def test_app_run_in_debug_starts_mongo_and_updates_settings(tmp_path, started):

	app = make_app(tmp_path / "shop")

	app.run(debug=True)

	assert started["mongo"] == [(str(tmp_path / "shop"), 5001, "7.0")]
	assert app.settings.mongo.url == "mongodb://127.0.0.1:5001/shop?replicaSet=rs0&directConnection=true"
	assert os.environ["DOMINO_MONGO__URL"] == app.settings.mongo.url
	assert len(started["run"]) == 1


def test_mongod_port_follows_the_app_port(tmp_path, started):

	make_app(tmp_path / "ported").run(port=8080, debug=True)

	assert started["mongo"][0][1] == 8081


def test_flask_debug_and_app_debug_count_as_debug(tmp_path, started, monkeypatch):

	monkeypatch.setenv("FLASK_DEBUG", "1")
	make_app(tmp_path / "env").run(load_dotenv=False)

	# The first run exported its URL, which the next app would otherwise read as mongo.url
	monkeypatch.delenv("DOMINO_MONGO__URL")
	monkeypatch.delenv("FLASK_DEBUG")
	app = make_app(tmp_path / "attr")
	app.debug = True
	app.run(load_dotenv=False)

	assert len(started["mongo"]) == 2


def test_app_run_without_debug_does_not_start_mongo(tmp_path, started):

	app = make_app(tmp_path / "prod")

	app.run()

	assert started["mongo"] == []
	assert "mongo" not in app.settings


def test_settings_mongo_url_wins(tmp_path, started):

	app = make_app(tmp_path / "remote", {"mongo": {"url": "mongodb://db.example/app"}})

	app.run(debug=True)

	assert started["mongo"] == []
	assert app.settings.mongo.url == "mongodb://db.example/app"


def test_mongo_auto_false_opts_out(tmp_path, started):

	app = make_app(tmp_path / "manual", {"mongo": {"auto": False}})

	app.run(debug=True)

	assert started["mongo"] == []
	assert "url" not in app.settings.mongo


def test_domino_no_mongo_env_opts_out(tmp_path, started, monkeypatch):

	monkeypatch.setenv("DOMINO_NO_MONGO", "1")

	make_app(tmp_path / "off").run(debug=True)

	assert started["mongo"] == []


def test_reloader_child_does_not_start_mongo(tmp_path, started, monkeypatch):

	# The parent already started mongod and exported the URL the child inherits
	monkeypatch.setenv("WERKZEUG_RUN_MAIN", "true")

	make_app(tmp_path / "child").run(debug=True)

	assert started["mongo"] == []
	assert len(started["run"]) == 1


def test_run_without_debug_serves_without_reloading(tmp_path, started):

	make_app(tmp_path / "prod").run(port=8000, threaded=True)

	# threaded is Werkzeug's and means nothing to uvicorn
	assert started["run"] == [{"host": "127.0.0.1", "port": 8000, "reload": False, "debug": False}]


def test_use_reloader_false_turns_reloading_off(tmp_path, started):

	make_app(tmp_path / "still").run(debug=True, use_reloader=False)

	assert started["run"][0]["reload"] is False


def test_flask_run_serves_the_app_itself(tmp_path, started, monkeypatch):

	monkeypatch.setenv("FLASK_RUN_FROM_CLI", "true")

	make_app(tmp_path / "flask").run(debug=True)

	assert started["run"] == []


# domino serve


@pytest.fixture
def workers_serve(monkeypatch):

	import domino.workers

	calls = []
	monkeypatch.setattr(domino.workers, "serve", lambda *args: calls.append(args) or 0)
	monkeypatch.setattr(domino.workers, "default_count", lambda: 6)

	return calls


def test_serve_starts_a_worker_per_core_without_loading_the_app(tmp_path, workers_serve, started):

	folder = tmp_path / "prod"
	write_app(folder)

	assert cli.main(["serve", str(folder), "--port", "9000"]) == 0

	assert workers_serve == [(str(folder.resolve()), "127.0.0.1", 9000, 6)]
	# Production: no local MongoDB, and the router process doesn't import the app
	assert started["mongo"] == [] and started["run"] == []


def test_serve_with_one_worker_serves_the_app_itself(tmp_path, workers_serve, started, capsys):

	path = write_app(tmp_path / "single")

	assert cli.main(["serve", str(path), "--workers", "1", "--host", "0.0.0.0"]) == 0

	assert workers_serve == []
	assert started["run"] == [{"host": "0.0.0.0", "port": 8000, "reload": False, "debug": False}]
	assert started["mongo"] == []
	assert "App: http://0.0.0.0:8000/ (1 worker)" in capsys.readouterr().err


def test_serve_checks_the_app_is_there(tmp_path, workers_serve, capsys):

	assert cli.main(["serve", str(tmp_path / "nope.py")]) == 1
	assert "No app at" in capsys.readouterr().err

	(tmp_path / "empty").mkdir()
	assert cli.main(["serve", str(tmp_path / "empty")]) == 1
	assert "No app.py or pages/ folder" in capsys.readouterr().err

	# A folder with just pages/ is an app
	(tmp_path / "pages_only" / "pages").mkdir(parents=True)
	assert cli.main(["serve", str(tmp_path / "pages_only")]) == 0
	assert workers_serve == [(str((tmp_path / "pages_only").resolve()), "127.0.0.1", 8000, 6)]


# Serving with uvicorn


@pytest.fixture
def uvicorn_runs(monkeypatch):

	import uvicorn

	calls = []
	monkeypatch.setattr(uvicorn, "run", lambda target, **kwargs: calls.append((target, kwargs)))

	return calls


def test_serve_without_reload_runs_the_asgi_app(tmp_path, uvicorn_runs):

	app = cli.find_app(cli.load_module(write_app(tmp_path / "plain")))

	domino.asgi.serve(app, "127.0.0.1", 5000)

	assert uvicorn_runs == [(app.asgi, {"host": "127.0.0.1", "port": 5000, "timeout_graceful_shutdown": 3})]
	assert "DOMINO_ASGI_APP" not in os.environ


def test_serve_with_reload_names_the_app_for_new_processes(tmp_path, uvicorn_runs):

	path = write_app(tmp_path / "reloading")
	app = cli.find_app(cli.load_module(path))
	app.debug = True

	domino.asgi.serve(app, "127.0.0.1", 5000, reload=True)

	((target, options),) = uvicorn_runs
	assert target == "domino.asgi:from_environ"
	assert options["factory"] is True and options["reload"] is True
	assert options["reload_dirs"] == [app.root_path]
	assert os.environ["DOMINO_ASGI_APP"] == f"{path.resolve()}:app"
	# The new process creates the app again, in debug mode too
	assert os.environ["FLASK_DEBUG"] == "1"


def test_serve_reload_needs_a_module_level_app(tmp_path, uvicorn_runs):

	app = make_app(tmp_path / "inline")

	domino.asgi.serve(app, "127.0.0.1", 5000, reload=True)

	assert uvicorn_runs[0][0] is app.asgi
	assert "reload" not in uvicorn_runs[0][1]


def test_from_environ_loads_the_app_from_its_file(tmp_path, monkeypatch):

	path = write_app(tmp_path / "child")
	monkeypatch.setenv("DOMINO_ASGI_APP", f"{path.resolve()}:app")

	asgi = domino.asgi.from_environ()

	assert asgi.app.root_path == str(tmp_path / "child")
	assert asgi.app is sys.modules[cli.module_name(path)].app


def test_from_environ_reuses_the_main_module(tmp_path, monkeypatch):

	# `python app.py`: the reloader's process has already run app.py as __main__
	path = write_app(tmp_path / "main")
	main = cli.load_module(path)
	monkeypatch.setitem(sys.modules, "__main__", main)
	monkeypatch.setattr(cli, "load_module", None)
	monkeypatch.setenv("DOMINO_ASGI_APP", f"{path.resolve()}:app")

	assert domino.asgi.from_environ() is main.app.asgi


def test_database_name_is_sanitized():

	assert devmongo.database_name("/srv/My App.v2") == "MyAppv2"
	assert devmongo.database_name("/srv/...") == "domino"


# Choosing a MongoDB build


def build(target, arch, edition, version):

	folder = {"macos": "osx", "windows": "windows"}.get(target, "linux")
	extension = {"windows": "zip"}.get(target, "tgz")
	name = f"mongodb-{target}-{arch}-{version}.{extension}"

	return {
		"target": target,
		"arch": arch,
		"edition": edition,
		"archive": {"url": f"https://fastdl.mongodb.org/{folder}/{name}", "sha256": f"sha-{target}-{arch}-{version}", "sha1": "x"},
	}


def release(version, production=True, candidate=False, targets=("ubuntu2204", "ubuntu2004", "debian12", "rhel8")):

	downloads = []
	for target in targets:
		downloads.append(build(target, "x86_64", "targeted", version))
		downloads.append(build(target, "aarch64", "targeted", version))
		downloads.append(build(target, "x86_64", "enterprise", version))
	downloads.append(build("macos", "x86_64", "base", version))
	downloads.append(build("macos", "arm64", "base", version))
	downloads.append(build("windows", "x86_64", "base", version))
	downloads.append(build("windows", "x86_64", "enterprise", version))

	return {"version": version, "production_release": production, "release_candidate": candidate, "downloads": downloads}


INDEX = {
	"versions": [
		release("8.0.4"),
		release("7.0.13-rc0", production=False, candidate=True),
		release("7.0.12"),
		release("7.0.9"),
		release("7.0.10"),
	]
}

INDEX_URL_FETCHED = "fetched"

UBUNTU_2204 = {"ID": "ubuntu", "VERSION_ID": "22.04", "PRETTY_NAME": "Ubuntu 22.04"}


def test_picks_the_newest_production_release_of_the_major_version():

	download = devmongo.select_download(INDEX, "7.0", "Linux", "x86_64", UBUNTU_2204)

	assert download["version"] == "7.0.12"
	assert download["target"] == "ubuntu2204"
	assert download["url"] == "https://fastdl.mongodb.org/linux/mongodb-ubuntu2204-x86_64-7.0.12.tgz"
	assert download["sha256"] == "sha-ubuntu2204-x86_64-7.0.12"
	assert download["note"] is None


def test_other_major_versions():

	assert devmongo.select_download(INDEX, "8.0", "Linux", "x86_64", UBUNTU_2204)["version"] == "8.0.4"

	with pytest.raises(devmongo.DevMongoError, match="No MongoDB 6.0"):
		devmongo.select_download(INDEX, "6.0", "Linux", "x86_64", UBUNTU_2204)


def test_linux_distros_and_arm():

	debian = {"ID": "debian", "VERSION_ID": "12"}
	rocky = {"ID": "rocky", "VERSION_ID": "8.9", "ID_LIKE": "rhel centos fedora"}

	assert devmongo.select_download(INDEX, "7.0", "Linux", "x86_64", debian)["target"] == "debian12"
	assert devmongo.select_download(INDEX, "7.0", "Linux", "x86_64", rocky)["target"] == "rhel8"

	arm = devmongo.select_download(INDEX, "7.0", "Linux", "aarch64", UBUNTU_2204)
	assert arm["url"].endswith("ubuntu2204-aarch64-7.0.12.tgz")


def test_newer_ubuntu_uses_the_newest_older_build():

	noble = {"ID": "ubuntu", "VERSION_ID": "24.04", "PRETTY_NAME": "Ubuntu 24.04"}

	download = devmongo.select_download(INDEX, "7.0", "Linux", "x86_64", noble)

	assert download["target"] == "ubuntu2204"
	assert "Ubuntu 24.04" in download["note"]


def test_unknown_distro_falls_back_to_ubuntu():

	arch_linux = {"ID": "arch", "PRETTY_NAME": "Arch Linux"}

	download = devmongo.select_download(INDEX, "7.0", "Linux", "x86_64", arch_linux)

	assert download["target"] == "ubuntu2204"
	assert "Arch Linux" in download["note"]


def test_macos_builds():

	intel = devmongo.select_download(INDEX, "7.0", "Darwin", "x86_64")
	apple = devmongo.select_download(INDEX, "7.0", "Darwin", "arm64")

	assert intel["url"] == "https://fastdl.mongodb.org/osx/mongodb-macos-x86_64-7.0.12.tgz"
	assert apple["url"] == "https://fastdl.mongodb.org/osx/mongodb-macos-arm64-7.0.12.tgz"


def test_windows_build_is_the_community_zip():

	download = devmongo.select_download(INDEX, "7.0", "Windows", "AMD64")

	assert download["url"] == "https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-7.0.12.zip"


def test_unsupported_platform():

	with pytest.raises(devmongo.DevMongoError, match="No MongoDB 7.0 build"):
		devmongo.select_download(INDEX, "7.0", "FreeBSD", "x86_64")


def test_parse_os_release():

	text = 'NAME="Ubuntu"\nID=ubuntu\nVERSION_ID="24.04"\n# comment\n'

	assert devmongo.parse_os_release(text) == {"NAME": "Ubuntu", "ID": "ubuntu", "VERSION_ID": "24.04"}


# Downloading


class FakeResponse(io.BytesIO):


	def __init__(self, data):

		super().__init__(data)

		self.headers = {"Content-Length": str(len(data))}


def fake_urlopen(data):

	def urlopen(url, timeout=None):

		return FakeResponse(data)

	return urlopen


def test_checksum_mismatch_fails_and_leaves_nothing_behind(tmp_path, monkeypatch, capsys):

	monkeypatch.setattr(devmongo.urllib.request, "urlopen", fake_urlopen(b"not mongodb"))
	download = {"version": "7.0.12", "target": "ubuntu2204", "url": "https://fastdl.mongodb.org/linux/m.tgz", "sha256": "0" * 64, "sha1": None}

	with pytest.raises(devmongo.DevMongoError, match="Checksum mismatch"):
		devmongo.download_archive(download, tmp_path)

	assert list(tmp_path.iterdir()) == []
	assert "100%" in capsys.readouterr().err


def test_sha1_is_used_when_there_is_no_sha256(tmp_path, monkeypatch):

	data = b"archive"
	monkeypatch.setattr(devmongo.urllib.request, "urlopen", fake_urlopen(data))
	download = {"version": "7.0.12", "target": "x", "url": "https://fastdl.mongodb.org/linux/m.tgz", "sha256": None, "sha1": hashlib.sha1(data).hexdigest()}

	archive = devmongo.download_archive(download, tmp_path)

	assert archive.read_bytes() == data


def test_ensure_mongod_downloads_once_and_extracts_only_mongod(tmp_path, monkeypatch):

	import tarfile

	bundle = tmp_path / "bundle.tgz"
	with tarfile.open(bundle, "w:gz") as tar:
		for name in ("mongod", "mongos"):
			source = tmp_path / name
			source.write_text(f"#!/bin/sh\necho {name}\n")
			tar.add(source, f"mongodb-linux-x86_64-ubuntu2204-7.0.12/bin/{name}")
	data = bundle.read_bytes()

	index = {"versions": [release("7.0.12")]}
	index["versions"][0]["downloads"] = [{
		"target": "ubuntu2204", "arch": "x86_64", "edition": "targeted",
		"archive": {"url": "https://fastdl.mongodb.org/linux/m.tgz", "sha256": hashlib.sha256(data).hexdigest()},
	}]
	fetches = []

	def fetch_index():

		fetches.append(INDEX_URL_FETCHED)
		return index

	monkeypatch.setattr(devmongo, "fetch_index", fetch_index)
	monkeypatch.setattr(devmongo, "read_os_release", lambda: UBUNTU_2204)
	monkeypatch.setattr(devmongo.platform, "system", lambda: "Linux")
	monkeypatch.setattr(devmongo.platform, "machine", lambda: "x86_64")
	monkeypatch.setattr(devmongo.urllib.request, "urlopen", fake_urlopen(data))
	home = {"DOMINO_HOME": str(tmp_path / "home")}

	path = devmongo.ensure_mongod("7.0", home)

	assert path == tmp_path / "home" / "mongodb" / "7.0.12" / "bin" / devmongo.binary_name()
	assert sorted(item.name for item in path.parent.parent.iterdir()) == ["bin"]
	assert os.access(path, os.X_OK)

	# Cached: found again without looking anything up
	assert devmongo.ensure_mongod("7.0", home) == path
	assert fetches == [INDEX_URL_FETCHED]


# A real MongoDB: downloads about 100MB the first time


@pytest.mark.skipif(os.environ.get("DOMINO_TEST_MONGO") != "1", reason="set DOMINO_TEST_MONGO=1 to download and run a real mongod")
def test_real_mongod_with_replica_set_and_change_streams(tmp_path, monkeypatch):

	import pymongo

	# Reuses the download across runs when DOMINO_TEST_HOME is set
	monkeypatch.setenv("DOMINO_HOME", os.environ.get("DOMINO_TEST_HOME") or str(tmp_path / "home"))
	app_folder = tmp_path / "integration-app"
	app_folder.mkdir()

	mongo = devmongo.DevMongo(app_folder, devmongo.free_port()).start()

	try:
		assert mongo.url.startswith(f"mongodb://127.0.0.1:{mongo.port}/integration-app?")
		assert (app_folder / ".domino" / "db").is_dir()
		assert (app_folder / ".domino" / "mongod.log").is_file()

		client = pymongo.MongoClient(mongo.url, serverSelectionTimeoutMS=5000)
		hello = client.admin.command("hello")
		assert hello["setName"] == "rs0"
		assert hello["isWritablePrimary"] is True

		status = client.admin.command("replSetGetStatus")
		assert status["members"][0]["stateStr"] == "PRIMARY"

		collection = client.get_default_database()["events"]
		with collection.watch(max_await_time_ms=500) as stream:
			collection.insert_one({"text": "hello"})
			change = None
			for _ in range(20):
				change = stream.try_next()
				if change is not None:
					break

		assert change["operationType"] == "insert"
		assert change["fullDocument"]["text"] == "hello"
		client.close()
	finally:
		process = mongo.process
		mongo.stop()

	assert process.poll() is not None
	assert not devmongo.pid_alive(process.pid)
	assert devmongo.port_free(mongo.port)


def test_a_folder_with_just_pages_reloads_too(tmp_path, uvicorn_runs, monkeypatch):

	folder = tmp_path / "bare"
	(folder / "pages").mkdir(parents=True)
	(folder / "pages" / "index.py").write_text("def page():\n\treturn 'hi'\n", encoding="utf-8")
	app = cli.load_app(folder)
	app.debug = True

	domino.asgi.serve(app, "127.0.0.1", 5000, reload=True)

	# The new process makes the app again from the folder, as `domino run` did
	((target, options),) = uvicorn_runs
	assert target == "domino.asgi:from_environ" and options["reload"] is True
	assert os.environ["DOMINO_ASGI_APP"] == str(folder.resolve())

	child = domino.asgi.from_environ()
	assert child.app is not app
	assert child.app.root_path == str(folder.resolve())
	assert child.app.test_client().get("/").get_data(as_text=True) == "hi"
