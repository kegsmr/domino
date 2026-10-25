"""`domino build` and `domino deploy`: the files they write, and the commands they run (through
deploy.run, replaced here, so nothing reaches Fly.io, Render or Docker)."""

import json
import os
import re
import shutil
import sys
import textwrap
import urllib.request

import pytest

import domino.cli as cli
import domino.deploy as deploy
from domino import Domino

from conftest import Served


VERSION = "9.8.7"

CMD = 'CMD ["domino", "serve", ".", "--host", "0.0.0.0", "--port", "8000"]'


def parse_toml(text):

	try:
		import tomllib
	except ImportError:
		try:
			import tomli as tomllib
		except ImportError:
			return simple_toml(text)

	return tomllib.loads(text)


def simple_toml(text):
	"""Enough of TOML for fly.toml, where Python has no tomllib (before 3.11): tables, arrays
	of tables, and strings, numbers and booleans."""

	data = {}
	table = data
	for line in text.splitlines():
		line = line.split("#", 1)[0].strip()
		if not line:
			continue
		match = re.fullmatch(r"(\[\[?)([\w.]+)\]\]?", line)
		if match:
			*parents, last = match.group(2).split(".")
			table = data
			for key in parents:
				table = table[key][-1] if isinstance(table[key], list) else table[key]
			if match.group(1) == "[[":
				table.setdefault(last, []).append({})
				table = table[last][-1]
			else:
				table = table.setdefault(last, {})
			continue
		key, value = (part.strip() for part in line.split("=", 1))
		assert re.fullmatch(r'"[^"]*"|\d+|true|false|\[.*\]', value), line
		table[key] = json.loads(value)

	return data


def parse_yaml(text):
	"""The YAML parsed, or None without PyYAML (the tests then check the text alone)."""

	try:
		import yaml
	except ImportError:
		return None

	return yaml.safe_load(text)


@pytest.fixture(autouse=True)
def clean_environ(monkeypatch):

	# The test database's URL (conftest.py) and the shell's settings would change what's found
	for name in list(os.environ):
		if name.startswith("DOMINO_") or name in ("MONGO_URL", "WEB_CONCURRENCY"):
			monkeypatch.delenv(name)

	monkeypatch.setattr(cli, "get_version", lambda: VERSION)
	# Never ask on a terminal
	monkeypatch.setattr(deploy, "prompt", lambda question: "")


@pytest.fixture
def app(tmp_path):
	"""An app folder; app(collections=True) gives it a named Collection."""

	def make(name="myapp", collections=False, settings=None, local_settings=None):

		folder = tmp_path / name
		folder.mkdir(parents=True)
		(folder / "app.py").write_text("from domino import Domino\n\napp = Domino(__name__)\n", encoding="utf-8")
		if collections:
			(folder / "data.py").write_text('from domino import Collection\n\ntasks = Collection("tasks")\n', encoding="utf-8")
		if settings is not None:
			(folder / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
		if local_settings is not None:
			(folder / "settings.local.json").write_text(json.dumps(local_settings), encoding="utf-8")

		return folder

	return make


class Commands:
	"""Stands in for deploy.run and shutil.which: records each command, and answers with the
	exit code and output given for the first words it starts with."""


	def __init__(self, monkeypatch, tools=("fly",), answers=None):

		self.calls = []
		self.answers = answers or {}
		self.tools = tools
		monkeypatch.setattr(deploy, "run", self.run)
		monkeypatch.setattr(shutil, "which", self.which)


	def which(self, name):

		return f"/usr/local/bin/{name}" if name in self.tools else None


	def run(self, command, cwd=None, capture=False):

		self.calls.append((command, cwd, capture))
		words = [os.path.basename(command[0])] + command[1:]
		for prefix, answer in self.answers.items():
			if words[:len(prefix.split())] == prefix.split():
				return answer
		return 0, ""


	@property
	def commands(self):

		return [[os.path.basename(command[0])] + command[1:] for command, _, _ in self.calls]


def files_text(folder):

	return "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in folder.rglob("*") if path.is_file())


# domino build


def test_apps_with_tailwind_build_its_css_into_the_image(app):

	plain = app("plain")
	styled = app("styled", settings={"tailwind": True})

	cli.main(["build", str(plain)])
	cli.main(["build", str(styled)])

	assert "tailwind" not in (plain / "Dockerfile").read_text()
	lines = (styled / "Dockerfile").read_text().splitlines()
	# After the app is copied in, as the user that runs it, so the CLI stays cached for it
	assert lines.index("RUN domino tailwind build") > lines.index("USER domino")


def test_build_writes_a_dockerfile(app, capsys):

	folder = app()

	assert cli.main(["build", str(folder)]) == 0

	dockerfile = (folder / "Dockerfile").read_text()
	lines = dockerfile.splitlines()
	assert "FROM python:3.12-slim" in lines
	assert "EXPOSE 8000" in lines
	assert lines[-1] == CMD
	# Not root
	assert "RUN useradd --create-home --uid 10001 domino" in lines
	assert lines.index("USER domino") < lines.index(CMD)
	assert "COPY --chown=domino:domino . ." in lines
	# Dependencies installed before the code is copied, so they're cached
	assert lines.index("COPY requirements.txt ./") < lines.index("RUN pip install -r requirements.txt") < lines.index("COPY --chown=domino:domino . .")
	assert "HEALTHCHECK" in dockerfile and "http://127.0.0.1:8000/_domino/health" in dockerfile
	assert "WEB_CONCURRENCY" in dockerfile

	# domino-web pinned to the version running
	assert (folder / "requirements.txt").read_text() == f"domino-web=={VERSION}\n"

	output = capsys.readouterr().out
	for name in ("Dockerfile", ".dockerignore", "requirements.txt"):
		assert f"Wrote    {name}" in output


def test_build_keeps_the_apps_requirements(app, capsys):

	folder = app()
	(folder / "requirements.txt").write_text("requests==2.31.0\n")

	deploy.build(folder)

	assert (folder / "requirements.txt").read_text() == "requests==2.31.0\n"
	assert f'RUN pip install -r requirements.txt "domino-web=={VERSION}"' in (folder / "Dockerfile").read_text()
	assert "Kept     requirements.txt" in capsys.readouterr().out

	# Already listed: its own pin is used
	(folder / "requirements.txt").write_text("domino-web==0.2.0\nrequests\n")
	deploy.build(folder, force=True)

	assert "RUN pip install -r requirements.txt\n" in (folder / "Dockerfile").read_text()
	assert (folder / "requirements.txt").read_text() == "domino-web==0.2.0\nrequests\n"


def test_build_overwrites_only_with_force(app, capsys):

	folder = app()
	deploy.build(folder)
	capsys.readouterr()

	(folder / "Dockerfile").write_text("FROM mine\n")
	(folder / ".dockerignore").write_text("mine\n")

	assert cli.main(["build", str(folder)]) == 0
	assert (folder / "Dockerfile").read_text() == "FROM mine\n"
	assert (folder / ".dockerignore").read_text() == "mine\n"
	assert "Kept     Dockerfile (already there; --force writes it again)" in capsys.readouterr().out

	assert cli.main(["build", str(folder), "--force"]) == 0
	assert (folder / "Dockerfile").read_text().splitlines()[-1] == CMD
	assert "settings.local.json" in (folder / ".dockerignore").read_text()
	# requirements.txt is the app's own: never written again
	(folder / "requirements.txt").write_text("domino-web\nmine\n")
	assert cli.main(["build", str(folder), "--force"]) == 0
	assert (folder / "requirements.txt").read_text() == "domino-web\nmine\n"
	output = capsys.readouterr().out
	assert "Wrote    Dockerfile" in output and "Kept     requirements.txt (already there)" in output


def test_dockerignore_keeps_secrets_and_local_data_out(app):

	folder = app()
	deploy.build(folder)

	patterns = [line for line in (folder / ".dockerignore").read_text().splitlines() if line and not line.startswith("#")]
	for pattern in ("settings.local.json", ".domino/", ".env", ".git/", ".venv/", "venv/", "**/__pycache__/"):
		assert pattern in patterns
	# The app's committed settings go in the image
	assert "settings.json" not in patterns


def test_build_serves_an_app_file_by_name(app):

	folder = app()
	(folder / "app.py").rename(folder / "server.py")

	assert cli.main(["build", str(folder / "server.py")]) == 0

	assert (folder / "Dockerfile").read_text().splitlines()[-1] == 'CMD ["domino", "serve", "server.py", "--host", "0.0.0.0", "--port", "8000"]'


def test_build_of_a_pages_only_app(tmp_path):

	(tmp_path / "site" / "pages").mkdir(parents=True)

	deploy.build(tmp_path / "site")

	assert (tmp_path / "site" / "Dockerfile").read_text().splitlines()[-1] == CMD


def test_build_without_a_known_version_leaves_domino_unpinned(app, monkeypatch, capsys):

	monkeypatch.setattr(cli, "get_version", lambda: "unknown")
	folder = app()

	deploy.build(folder)

	assert (folder / "requirements.txt").read_text() == "domino-web\n"
	assert "couldn't tell which domino-web version" in capsys.readouterr().err


# domino deploy fly


def test_fly_toml(app, monkeypatch):

	folder = app("My App")
	Commands(monkeypatch, tools=())

	deploy.deploy_fly(folder)

	config = parse_toml((folder / "fly.toml").read_text())
	assert re.fullmatch(r"my-app-[0-9a-f]{4}", config["app"])
	assert config["build"]["dockerfile"] == "Dockerfile"
	service = config["http_service"]
	assert service["internal_port"] == 8000
	assert service["force_https"] is True
	assert service["auto_start_machines"] is True
	assert [(check["method"], check["path"]) for check in service["checks"]] == [("GET", "/_domino/health")]
	assert config["vm"][0]["memory"] == "512mb"
	assert (folder / "Dockerfile").is_file()


def test_the_toml_fallback_reads_fly_toml_as_tomllib_does(app, monkeypatch):

	tomllib = pytest.importorskip("tomllib")
	folder = app()
	Commands(monkeypatch, tools=())

	deploy.deploy_fly(folder)

	text = (folder / "fly.toml").read_text()
	assert simple_toml(text) == tomllib.loads(text)


def test_fly_keeps_the_app_name_in_fly_toml(app, monkeypatch):

	folder = app()
	commands = Commands(monkeypatch)

	deploy.deploy_fly(folder, name="Shop Front")
	assert parse_toml((folder / "fly.toml").read_text())["app"] == "shop-front"

	deploy.deploy_fly(folder)
	assert ["fly", "deploy", "--app", "shop-front", "--ha=false"] in commands.commands

	with pytest.raises(deploy.DeployError, match='fly.toml is for the app "shop-front"'):
		deploy.deploy_fly(folder, name="other")

	deploy.deploy_fly(folder, name="other", force=True)
	assert parse_toml((folder / "fly.toml").read_text())["app"] == "other"


def test_deploy_fly_launches_sets_secrets_and_deploys(app, monkeypatch, capsys):

	folder = app(collections=True)
	commands = Commands(monkeypatch, answers={"fly status": (1, "Could not find App")})

	assert cli.main(["deploy", "fly", str(folder), "--name", "shop", "--mongo-url", "mongodb+srv://u:pw@cluster.example.net/shop"]) == 0

	assert [command[:4] for command in commands.commands] == [
		["fly", "auth", "whoami"],
		["fly", "status", "--app", "shop"],
		["fly", "launch", "--no-deploy", "--copy-config"],
		["fly", "secrets", "set", "--app"],
		["fly", "deploy", "--app", "shop"],
	]
	secrets_set = commands.commands[3]
	assert secrets_set[:6] == ["fly", "secrets", "set", "--app", "shop", "--stage"]
	key = secrets_set[6]
	assert re.fullmatch(r"DOMINO_SECRET_KEY=[\w-]{60,}", key)
	assert secrets_set[7:] == ["DOMINO_MONGO__URL=mongodb+srv://u:pw@cluster.example.net/shop"]
	assert commands.commands[4] == ["fly", "deploy", "--app", "shop", "--ha=false"]

	# Run in the app's folder, quietly only for the checks
	assert {cwd for _, cwd, _ in commands.calls} == {str(folder)}
	assert [capture for _, _, capture in commands.calls] == [True, True, False, False, False]

	# Secrets are passed to flyctl, never written into the app's files
	text = files_text(folder)
	assert key.split("=", 1)[1] not in text
	assert "pw@cluster" not in text

	captured = capsys.readouterr()
	assert "https://shop.fly.dev/" in captured.out
	assert "no MongoDB URL" not in captured.err


def test_deploy_fly_keeps_the_secret_key_already_set(app, monkeypatch, capsys):

	folder = app(collections=True)
	listed = "NAME                 \tDIGEST          \tCREATED AT\nDOMINO_SECRET_KEY    \t1a2b3c4d5e6f    \t2026-10-01\n"
	commands = Commands(monkeypatch, answers={"fly secrets list": (0, listed)})
	monkeypatch.setenv("DOMINO_MONGO__URL", "mongodb+srv://cluster.example.net/app")

	deploy.deploy_fly(folder, name="app")

	assert commands.commands == [
		["fly", "auth", "whoami"],
		["fly", "status", "--app", "app"],
		["fly", "secrets", "list", "--app", "app"],
		["fly", "secrets", "set", "--app", "app", "--stage", "DOMINO_MONGO__URL=mongodb+srv://cluster.example.net/app"],
		["fly", "deploy", "--app", "app", "--ha=false"],
	]
	assert "MongoDB URL from DOMINO_MONGO__URL" in capsys.readouterr().out

	# Both set already: nothing to set
	listed += "DOMINO_MONGO__URL    \t9f8e7d6c5b4a    \t2026-10-01\n"
	commands = Commands(monkeypatch, answers={"fly secrets list": (0, listed)})
	monkeypatch.delenv("DOMINO_MONGO__URL")

	deploy.deploy_fly(folder, name="app")

	assert [command[:3] for command in commands.commands] == [["fly", "auth", "whoami"], ["fly", "status", "--app"], ["fly", "secrets", "list"], ["fly", "deploy", "--app"]]
	assert "no MongoDB URL" not in capsys.readouterr().err


def test_deploy_fly_uses_the_secret_key_in_the_environment(app, monkeypatch):

	folder = app()
	commands = Commands(monkeypatch, tools=("flyctl",))
	monkeypatch.setenv("DOMINO_SECRET_KEY", "from the environment")

	deploy.deploy_fly(folder, name="app")

	assert commands.calls[0][0][0] == "/usr/local/bin/flyctl"
	assert ["flyctl", "secrets", "set", "--app", "app", "--stage", "DOMINO_SECRET_KEY=from the environment"] in commands.commands


def test_deploy_fly_without_flyctl_asks_for_the_mongo_url_when_needed(app, monkeypatch, capsys):

	Commands(monkeypatch, tools=())

	deploy.deploy_fly(app(collections=True), name="app")

	line = [line for line in capsys.readouterr().out.splitlines() if "fly secrets set" in line][0]
	assert line.endswith("DOMINO_MONGO__URL='mongodb+srv://...'")


def test_deploy_fly_stops_if_the_secrets_cant_be_listed(app, monkeypatch):

	folder = app()
	commands = Commands(monkeypatch, answers={"fly secrets list": (1, "Error: connection refused")})

	# Rather than set a new secret key, which would sign everyone out
	with pytest.raises(deploy.DeployError, match="connection refused"):
		deploy.deploy_fly(folder, name="app")

	assert commands.commands[-1][:3] == ["fly", "secrets", "list"]


def test_deploy_fly_logs_in_first(app, monkeypatch):

	folder = app()
	commands = Commands(monkeypatch, answers={"fly auth whoami": (1, "not logged in")})

	deploy.deploy_fly(folder, name="app")

	assert commands.commands[:3] == [["fly", "auth", "whoami"], ["fly", "auth", "login"], ["fly", "status", "--app", "app"]]


def test_deploy_fly_stops_when_a_command_fails(app, monkeypatch, capsys):

	folder = app()
	commands = Commands(monkeypatch, answers={"fly status": (1, ""), "fly launch": (1, "")})

	assert cli.main(["deploy", "fly", str(folder), "--name", "app"]) == 1

	assert commands.commands[-1][:2] == ["fly", "launch"]
	assert "fly launch failed" in capsys.readouterr().err


def test_deploy_fly_asks_for_the_mongo_url(app, monkeypatch):

	folder = app(collections=True)
	commands = Commands(monkeypatch)
	questions = []
	monkeypatch.setattr(deploy, "prompt", lambda question: questions.append(question) or "mongodb+srv://typed.example.net/app")

	deploy.deploy_fly(folder, name="app")

	assert questions and "MongoDB URL" in questions[0]
	assert commands.commands[3][-1] == "DOMINO_MONGO__URL=mongodb+srv://typed.example.net/app"


def test_deploy_fly_reads_the_mongo_url_from_settings_local_json(app, monkeypatch, capsys):

	folder = app(collections=True, local_settings={"mongo": {"url": "mongodb+srv://local-file.example.net/app"}})
	commands = Commands(monkeypatch)

	deploy.deploy_fly(folder, name="app")

	assert commands.commands[3][-1] == "DOMINO_MONGO__URL=mongodb+srv://local-file.example.net/app"
	assert "MongoDB URL from settings.local.json" in capsys.readouterr().out


def test_deploy_fly_without_flyctl_prints_the_steps(app, monkeypatch, capsys):

	folder = app()
	commands = Commands(monkeypatch, tools=())

	assert cli.main(["deploy", "fly", str(folder), "--name", "app"]) == 0

	assert commands.calls == []
	output = capsys.readouterr().out
	assert "isn't installed" in output
	assert deploy.FLY_INSTALL_URL in output
	assert "fly launch --no-deploy --copy-config" in output
	assert "fly secrets set --app app --stage DOMINO_SECRET_KEY=" in output
	assert "DOMINO_MONGO__URL" not in output.split("fly secrets set")[1].splitlines()[0]
	assert "fly deploy --app app --ha=false" in output
	assert "replica set" in output and deploy.ATLAS_URL in output


# domino deploy render


def test_render_yaml(app, monkeypatch, capsys):

	folder = app("Shop")
	commands = Commands(monkeypatch, tools=())

	assert cli.main(["deploy", "render", str(folder)]) == 0

	text = (folder / "render.yaml").read_text()
	for line in ("  - type: web", "    runtime: docker", "    healthCheckPath: /_domino/health", "        generateValue: true", "        sync: false"):
		assert line + "\n" in text

	blueprint = parse_yaml(text)
	if blueprint is None:
		return
	service, = blueprint["services"]
	assert (service["type"], service["name"], service["runtime"]) == ("web", "shop", "docker")
	assert service["healthCheckPath"] == "/_domino/health"
	assert "rootDir" not in service
	env = {var["key"]: var for var in service["envVars"]}
	assert env["DOMINO_SECRET_KEY"] == {"key": "DOMINO_SECRET_KEY", "generateValue": True}
	assert env["DOMINO_MONGO__URL"] == {"key": "DOMINO_MONGO__URL", "sync": False}
	assert env["PORT"]["value"] == "8000"
	assert (folder / "Dockerfile").is_file()
	assert commands.calls == []

	output = capsys.readouterr().out
	assert "Render deploys Blueprints from its dashboard" in output
	assert "git push" in output and "New > Blueprint" in output
	assert "DOMINO_MONGO__URL" in output


def test_render_yaml_for_an_app_in_a_subfolder_of_the_repository(tmp_path, app, capsys):

	(tmp_path / ".git").mkdir()
	folder = app("apps/web")

	deploy.deploy_render(folder)

	text = (folder / "render.yaml").read_text()
	assert "    rootDir: apps/web\n" in text
	assert "Blueprint path to apps/web/render.yaml" in capsys.readouterr().out

	service = (parse_yaml(text) or {"services": [{"rootDir": "apps/web", "dockerContext": "./apps/web", "dockerfilePath": "./apps/web/Dockerfile"}]})["services"][0]
	assert service["rootDir"] == "apps/web"
	assert service["dockerContext"] == "./apps/web"
	assert service["dockerfilePath"] == "./apps/web/Dockerfile"


# domino deploy docker


def test_docker_compose_runs_mongo_as_a_replica_set(app, monkeypatch):

	folder = app("Shop", collections=True)
	Commands(monkeypatch, tools=())

	deploy.deploy_docker(folder)

	text = (folder / "docker-compose.yml").read_text()
	assert 'command: ["--replSet", "rs0", "--bind_ip_all"]' in text
	assert "mongodb://mongo:27017/shop?replicaSet=rs0" in text
	assert "      - mongo-data:/data/db\n" in text

	compose = parse_yaml(text)
	if compose is None:
		return
	app_service, mongo = compose["services"]["app"], compose["services"]["mongo"]
	assert app_service["build"] == "."
	assert app_service["ports"] == ["8000:8000"]
	assert app_service["environment"]["DOMINO_MONGO__URL"] == "mongodb://mongo:27017/shop?replicaSet=rs0"
	assert app_service["environment"]["DOMINO_SECRET_KEY"].startswith("${DOMINO_SECRET_KEY:?")
	assert app_service["depends_on"] == {"mongo": {"condition": "service_healthy"}}

	assert mongo["command"][:2] == ["--replSet", "rs0"]
	assert mongo["volumes"] == ["mongo-data:/data/db"]
	assert "mongo-data" in compose["volumes"]
	# The health check starts the replica set the first time
	assert "rs.initiate" in " ".join(mongo["healthcheck"]["test"])
	assert "host: 'mongo:27017'" in " ".join(mongo["healthcheck"]["test"])


def test_deploy_docker_builds_the_image(app, monkeypatch, capsys):

	folder = app("Shop")
	commands = Commands(monkeypatch, tools=("docker",))

	assert cli.main(["deploy", "docker", str(folder)]) == 0

	assert commands.commands == [["docker", "info"], ["docker", "build", "-t", "shop", "."]]
	assert commands.calls[1][1] == str(folder)
	output = capsys.readouterr().out
	assert "Building the image shop" in output
	assert "docker run -p 8000:8000 -e DOMINO_SECRET_KEY -e DOMINO_MONGO__URL shop" in output
	assert "export DOMINO_SECRET_KEY=" in output
	assert "docker compose up -d" in output
	assert "DOMINO_DOMINO__SECURE_COOKIES=false" in output


def test_deploy_docker_without_docker_prints_the_build_command(app, monkeypatch, capsys):

	folder = app("Shop")

	commands = Commands(monkeypatch, tools=())
	deploy.deploy_docker(folder)
	assert commands.calls == []
	output = capsys.readouterr().out
	assert "Docker isn't installed" in output
	assert f"docker build -t shop {folder}" in output

	# Installed, but its daemon isn't running
	commands = Commands(monkeypatch, tools=("docker",), answers={"docker info": (1, "Cannot connect")})
	deploy.deploy_docker(folder)
	assert commands.commands == [["docker", "info"]]
	assert "Docker isn't running" in capsys.readouterr().out


def test_deploy_docker_stops_when_the_build_fails(app, monkeypatch, capsys):

	folder = app()
	Commands(monkeypatch, tools=("docker",), answers={"docker build": (1, "")})

	assert cli.main(["deploy", "docker", str(folder)]) == 1
	assert "docker build failed" in capsys.readouterr().err


# Warnings


@pytest.mark.parametrize("platform", ["fly", "render", "docker"])
def test_warns_about_collections_without_a_mongo_url(app, monkeypatch, capsys, platform):

	Commands(monkeypatch, tools=())

	deploy.deploy(platform, app("with", collections=True))
	assert "uses named Collections (MongoDB), but no MongoDB URL" in capsys.readouterr().err

	deploy.deploy(platform, app("given", collections=True), mongo_url="mongodb+srv://db.example.net/x")
	assert "no MongoDB URL" not in capsys.readouterr().err

	deploy.deploy(platform, app("committed", collections=True, settings={"mongo": {"url": "mongodb://db.example.net/x"}}))
	assert "no MongoDB URL" not in capsys.readouterr().err

	deploy.deploy(platform, app("without"))
	assert "no MongoDB URL" not in capsys.readouterr().err


def test_a_local_mongo_url_is_not_used_for_production(app, monkeypatch, capsys):

	Commands(monkeypatch, tools=())
	folder = app(collections=True, local_settings={"mongo": {"url": "mongodb://127.0.0.1:5001/myapp?replicaSet=rs0"}})

	assert deploy.find_mongo_url(folder) == (None, None)
	deploy.deploy_render(folder)

	captured = capsys.readouterr()
	assert "is a local database" in captured.out
	assert "no MongoDB URL" in captured.err


def test_finds_collections_cheaply(app):

	assert deploy.uses_collections(app("a", collections=True))
	assert not deploy.uses_collections(app("b"))

	# In-memory collections and other folders don't count
	folder = app("c")
	(folder / "data.py").write_text("from domino import Collection\n\nlocal = Collection()\n")
	(folder / ".venv" / "lib").mkdir(parents=True)
	(folder / ".venv" / "lib" / "x.py").write_text('Collection("x")\n')
	assert not deploy.uses_collections(folder)


@pytest.mark.parametrize("platform", ["fly", "render", "docker"])
def test_warns_about_a_secret_key_in_settings_json(app, monkeypatch, capsys, platform):

	Commands(monkeypatch, tools=())

	deploy.deploy(platform, app("committed", settings={"secret_key": "oops"}))
	assert "settings.json has a secret_key" in capsys.readouterr().err

	deploy.deploy(platform, app("local", local_settings={"secret_key": "fine"}))
	assert "secret_key" not in capsys.readouterr().err


# /_domino/health


HEALTH_APP = '''
from domino import Domino


app = Domino(__name__)
'''


def test_health_over_wsgi(tmp_path):

	app = Domino(__name__, root_path=str(tmp_path))
	app.secret_key = "health"
	client = app.test_client()

	response = client.get("/_domino/health")

	assert response.status_code == 200
	assert response.data == b"ok"
	assert response.mimetype == "text/plain"
	assert response.headers["Cache-Control"] == "no-store"
	assert "Set-Cookie" not in response.headers
	assert app.page_store.pages == {}
	assert client.head("/_domino/health").status_code == 200


def test_health_over_asgi(tmp_path, asgi_server):

	app = Domino(__name__, root_path=str(tmp_path))
	server = asgi_server(app)

	with urllib.request.urlopen(server.url + "_domino/health", timeout=10) as response:
		assert (response.status, response.read()) == (200, b"ok")

	assert app.page_store.pages == {}


@pytest.mark.skipif(sys.platform == "win32", reason="uses POSIX signals")
def test_health_through_the_serve_router(tmp_path):

	folder = tmp_path / "app"
	folder.mkdir()
	(folder / "app.py").write_text(textwrap.dedent(HEALTH_APP), encoding="utf-8")

	served = Served(folder, 2)
	try:
		served.start()
		# Each goes to whichever worker is free; every one answers
		for _ in range(6):
			assert served.get("/_domino/health") == "ok"
	finally:
		served.stop()
