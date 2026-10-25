"""`domino build` and `domino deploy`: an app folder made ready for a container platform, like
`meteor deploy` but without lock-in. `build` writes a Dockerfile (the app served by `domino
serve`), and `deploy fly|render|docker` adds that platform's file and runs (or prints) the rest.

Secrets (the secret key, the MongoDB URL) are only ever passed to the platform's command or
printed, never written into the app's files, which are meant to be committed."""

import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from .settings import SettingsError, read_file


def shell_quote(path):
	"""A path to paste into a shell: quoted for sh, or for cmd and PowerShell on Windows."""

	if os.name == "nt":
		return subprocess.list2cmdline([str(path)])

	return shlex.quote(str(path))


PORT = 8000

HEALTH_PATH = "/_domino/health"

FLY_INSTALL_URL = "https://fly.io/docs/flyctl/install/"
RENDER_BLUEPRINTS_URL = "https://dashboard.render.com/blueprints"
ATLAS_URL = "https://www.mongodb.com/cloud/atlas"

# Folders that aren't the app's code: not scanned, and kept out of the image
SKIPPED_FOLDERS = {".git", ".domino", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache"}

DOCKERFILE_TEMPLATE = '''\
# Written by `domino build`: the app, served by `domino serve` on port {port}.
# Edit it as you like; `domino build --force` writes it again.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \\
    PYTHONDONTWRITEBYTECODE=1 \\
    PIP_NO_CACHE_DIR=1 \\
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/app

# Dependencies first, so changing the app's code doesn't install them again
COPY requirements.txt ./
RUN pip install {install}

# The app runs as a user without root rights
RUN useradd --create-home --uid 10001 domino
COPY --chown=domino:domino . .
USER domino
{tailwind}
EXPOSE {port}

# One worker process per CPU core; set WEB_CONCURRENCY (e.g. -e WEB_CONCURRENCY=2) to choose
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \\
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:{port}{health}', timeout=4)"]

CMD ["domino", "serve", "{target}", "--host", "0.0.0.0", "--port", "{port}"]
'''

DOCKERIGNORE_TEMPLATE = '''\
# Kept out of the image by `domino build`: local data, secrets, caches and virtualenvs
.domino/
settings.local.json
*.local.json
.env
.env.*
**/__pycache__/
**/*.py[co]
.git/
.venv/
venv/
.pytest_cache/
node_modules/
*.log
'''

FLY_TEMPLATE = '''\
# Written by `domino deploy fly`. See https://fly.io/docs/reference/configuration/
app = "{name}"

[build]
  dockerfile = "Dockerfile"

[env]
  # Fly's proxy connects from private addresses and adds the visitor's to X-Forwarded-For.
  # Trusting it (and only it) lets the per-visitor limits on logins and emails tell visitors
  # apart; never "*", which would trust what visitors send
  FORWARDED_ALLOW_IPS = "{proxies}"
  # Links in emails (password resets) are built on it; change it for a domain of your own
  DOMINO_PUBLIC_URL = "https://{name}.fly.dev"

[http_service]
  internal_port = {port}
  force_https = true
  # Idle machines stop and start again on the next request; open pages then reload
  auto_stop_machines = "stop"
  auto_start_machines = true
  min_machines_running = 0

  [http_service.concurrency]
    # Each open tab keeps a WebSocket connection
    type = "connections"
    soft_limit = 800
    hard_limit = 1000

  [[http_service.checks]]
    method = "GET"
    path = "{health}"
    interval = "30s"
    timeout = "5s"
    grace_period = "20s"

[[vm]]
  memory = "512mb"
  cpu_kind = "shared"
  cpus = 1
'''

RENDER_TEMPLATE = '''\
# Written by `domino deploy render`: a Render Blueprint. Push it to GitHub, then create a
# "New Blueprint" from the repository in the Render dashboard. See https://render.com/docs/blueprint-spec
services:
  - type: web
    name: {name}
    runtime: docker
    plan: free
{paths}    healthCheckPath: {health}
    envVars:
      - key: DOMINO_SECRET_KEY
        generateValue: true
      - key: DOMINO_MONGO__URL
        sync: false
      - key: PORT
        value: "{port}"
      # Worker processes; raise it on plans with more CPU
      - key: WEB_CONCURRENCY
        value: "1"
      # Render's proxy connects from private addresses and adds the visitor's to X-Forwarded-For.
      # Trusting it (and only it) lets the per-visitor limits on logins and emails tell visitors
      # apart; never "*", which would trust what visitors send
      - key: FORWARDED_ALLOW_IPS
        value: "{proxies}"
'''

# Private networks, where platform proxies connect from (uvicorn and the router take the
# visitor's address as the last one in X-Forwarded-For that isn't one of these)
PLATFORM_PROXIES = "127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"

COMPOSE_TEMPLATE = '''\
# Written by `domino deploy docker`: the app and a MongoDB for it, on http://localhost:{port}.
#   export DOMINO_SECRET_KEY=...   (a long random string, kept the same between runs)
#   docker compose up -d
services:
  app:
    build: .
    image: {name}
    ports:
      - "{port}:{port}"
    environment:
      DOMINO_SECRET_KEY: ${{DOMINO_SECRET_KEY:?set DOMINO_SECRET_KEY to a long random string}}
      DOMINO_MONGO__URL: "mongodb://mongo:27017/{database}?replicaSet=rs0"
      # Plain HTTP on localhost; remove this behind HTTPS
      DOMINO_DOMINO__SECURE_COOKIES: "false"
    depends_on:
      mongo:
        condition: service_healthy
    restart: unless-stopped

  mongo:
    image: mongo:7.0
    # A single-node replica set, which change streams (live updates across workers) need
    command: ["--replSet", "rs0", "--bind_ip_all"]
    volumes:
      - mongo-data:/data/db
    healthcheck:
      # Starts the replica set the first time, then reports healthy once it's the primary
      test: ["CMD", "mongosh", "--quiet", "--eval", "try {{ rs.status() }} catch (e) {{ rs.initiate({{_id: 'rs0', members: [{{_id: 0, host: 'mongo:27017'}}]}}) }}; quit(db.hello().isWritablePrimary ? 0 : 1)"]
      interval: 5s
      timeout: 10s
      start_period: 10s
      retries: 30
    restart: unless-stopped

volumes:
  mongo-data:
'''

MONGO_NOTE = f'''\
MongoDB: named Collections need a MongoDB that runs as a replica set (live updates use its
change streams). MongoDB Atlas is one, free tier included: {ATLAS_URL}
Its connection string (mongodb+srv://...) goes in DOMINO_MONGO__URL.'''


class DeployError(RuntimeError):
	"""Something `domino build` or `domino deploy` can't go on without."""


def say(message=""):

	print(message, flush=True)


def warn(message):

	print(f"domino: warning: {message}", file=sys.stderr, flush=True)


def run(command, cwd=None, capture=False):
	"""Run an outside command (docker, flyctl). Every one goes through here, so tests can
	replace it. Returns (exit code, output); output is only captured when asked."""

	try:
		result = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE if capture else None, stderr=subprocess.STDOUT if capture else None, text=True)
	except OSError as error:
		raise DeployError(f"Couldn't run {command[0]}: {error}") from None

	return result.returncode, result.stdout or ""


def prompt(question):
	"""Ask on the terminal; "" when there's none to ask on."""

	if not sys.stdin or not sys.stdin.isatty():
		return ""

	try:
		return input(question).strip()
	except EOFError:
		return ""


def new_secret_key():

	return secrets.token_urlsafe(48)


# The app


def app_target(path):
	"""The app's folder, and what `domino serve` is given inside the image: "." for a folder
	(its app.py or pages/), or the file's name for another app file."""

	path = Path(path).resolve()

	if path.is_file():
		return path.parent, "." if path.name == "app.py" else path.name

	if not path.is_dir():
		raise DeployError(f"No app at {path} (pass the app's folder)")
	if not (path / "app.py").is_file() and not (path / "pages").is_dir():
		raise DeployError(f"No app.py or pages/ folder in {path}")

	return path, "."


def slug(name):
	"""A name platforms accept for apps and images: lowercase letters, digits and dashes."""

	return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-") or "domino-app"


def python_files(folder):

	for root, folders, files in os.walk(folder):
		folders[:] = [name for name in folders if name not in SKIPPED_FOLDERS and not name.startswith(".")]
		for name in files:
			if name.endswith(".py"):
				yield Path(root) / name


def uses_collections(folder):
	"""Whether the app has named Collections (MongoDB). A cheap guess from its source."""

	pattern = re.compile(r"""\bCollection\(\s*["']""")

	for path in python_files(folder):
		try:
			if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
				return True
		except OSError:
			continue

	return False


def read_settings_file(path):

	try:
		return read_file(path)
	except SettingsError as error:
		warn(str(error))
		return {}


def setting(data, *keys):

	for key in keys:
		if not isinstance(data, dict):
			return None
		data = data.get(key)

	return data


def is_local_url(url):

	host = re.sub(r"^[a-z+]+://([^/@]*@)?", "", url).split("/")[0].split(",")[0]

	return host.split(":")[0].strip("[]") in ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def find_mongo_url(folder, given=None, environ=None):
	"""The production MongoDB URL and where it came from: --mongo-url, the environment, or
	settings.local.json (unless that's a local database). (None, None) if there's none."""

	if environ is None:
		environ = os.environ

	if given:
		return given, "--mongo-url"

	for name in ("DOMINO_MONGO__URL", "MONGO_URL"):
		if environ.get(name):
			return environ[name], name

	local = setting(read_settings_file(folder / "settings.local.json"), "mongo", "url")
	if isinstance(local, str) and local:
		if not is_local_url(local):
			return local, "settings.local.json"
		say("settings.local.json's mongo.url is a local database, so it isn't used for production.")

	return None, None


def committed_mongo_url(folder):

	return setting(read_settings_file(folder / "settings.json"), "mongo", "url")


def check_app(folder, mongo_configured, note=""):
	"""Warnings about the app's settings before it's deployed."""

	if "secret_key" in read_settings_file(folder / "settings.json"):
		warn("settings.json has a secret_key, and settings.json is committed with your code. "
			"Remove it and keep it in DOMINO_SECRET_KEY (or settings.local.json) instead; "
			"the DOMINO_SECRET_KEY set on the platform wins over it.")

	if not mongo_configured and not committed_mongo_url(folder) and uses_collections(folder):
		warn("this app uses named Collections (MongoDB), but no MongoDB URL is configured for production. "
			f"Pass --mongo-url, set DOMINO_MONGO__URL, or put mongo.url in settings.local.json.{note}")


# domino build


def domino_requirement():
	"""domino-web pinned to the version running, so the image gets the same one."""

	from .cli import get_version

	version = get_version()
	if version == "unknown" or "+" in version:
		warn(f"couldn't tell which domino-web version this is ({version}), so the image gets the newest one")
		return "domino-web"

	return f"domino-web=={version}"


def requires_domino(text):

	return re.search(r"^\s*domino[-_.]web\b", text, re.IGNORECASE | re.MULTILINE) is not None


def write_file(path, text, force=False, keep=False):
	"""Write one deployment file unless it's there (and not `force`d). Returns whether it did."""

	if path.exists() and (keep or not force):
		hint = "" if keep else "; --force writes it again"
		say(f"Kept     {path.name} (already there{hint})")
		return False

	path.write_text(text, encoding="utf-8")
	say(f"Wrote    {path.name}")

	return True


def tailwind_step(folder):
	"""The Dockerfile lines that build the app's Tailwind CSS into the image, if it uses Tailwind."""

	from . import tailwind
	from .settings import load_settings

	if not tailwind.options(load_settings(str(folder)), str(folder)):
		return ""

	# Built once here (the CLI stays cached in the image), so the server starts with it ready
	return "\n# Tailwind's CSS, built into the image\nRUN domino tailwind build\n"


def build(path, force=False):
	"""Write the Dockerfile, .dockerignore and (if missing) requirements.txt. Returns the
	app's folder."""

	folder, target = app_target(path)
	requirement = domino_requirement()

	requirements = folder / "requirements.txt"
	has_requirements = requirements.is_file()

	# The app's own requirements.txt is kept as it is; domino-web is added unless it's listed
	install = "-r requirements.txt"
	if has_requirements and not requires_domino(requirements.read_text(encoding="utf-8", errors="replace")):
		install += f' "{requirement}"'

	dockerfile = DOCKERFILE_TEMPLATE.format(port=PORT, health=HEALTH_PATH, install=install, target=target, tailwind=tailwind_step(folder))

	say(f"Deployment files in {folder}:")
	write_file(folder / "Dockerfile", dockerfile, force)
	write_file(folder / ".dockerignore", DOCKERIGNORE_TEMPLATE, force)
	write_file(requirements, requirement + "\n", keep=True)

	return folder


# domino deploy fly


def fly_app_name(folder, name=None, force=False):

	path = folder / "fly.toml"
	if path.is_file() and not force:
		match = re.search(r"""^app\s*=\s*["']([^"']+)["']""", path.read_text(encoding="utf-8"), re.MULTILINE)
		if match:
			if name and slug(name) != match.group(1):
				raise DeployError(f'fly.toml is for the app "{match.group(1)}"; pass --force to write it for "{slug(name)}"')
			return match.group(1)

	if name:
		return slug(name)

	# Fly app names are global, so a new one gets a random ending to be free
	return f"{slug(folder.name)[:30]}-{secrets.token_hex(2)}"


def fly_commands(app, mongo, collections):
	"""The commands `domino deploy fly` runs, written out for running by hand."""

	key = '"$(python -c \'import secrets; print(secrets.token_urlsafe(48))\')"'
	values = f"DOMINO_SECRET_KEY={key}"
	if mongo or collections:
		values += " DOMINO_MONGO__URL=" + (shlex.quote(mongo) if mongo else "'mongodb+srv://...'")

	return [
		"fly launch --no-deploy --copy-config",
		f"fly secrets set --app {app} --stage {values}",
		f"fly deploy --app {app} --ha=false",
	]


def deploy_fly(path, name=None, mongo_url=None, force=False, environ=None):

	if environ is None:
		environ = os.environ

	folder = build(path, force)
	app = fly_app_name(folder, name, force)
	write_file(folder / "fly.toml", FLY_TEMPLATE.format(name=app, port=PORT, health=HEALTH_PATH, proxies=PLATFORM_PROXIES), force)
	say()

	mongo, source = find_mongo_url(folder, mongo_url, environ)
	if mongo:
		say(f"MongoDB URL from {source}")

	fly = shutil.which("flyctl") or shutil.which("fly")
	if not fly:
		check_app(folder, mongo)
		commands = "\n".join(f"    {command}" for command in fly_commands(app, mongo, uses_collections(folder)))
		say(f"flyctl, Fly.io's command, isn't installed. To deploy:\n\n"
			f"1. Install it: {FLY_INSTALL_URL}\n"
			f"2. Run `domino deploy fly` again, or run these yourself:\n\n"
			f"    cd {shell_quote(folder)}\n{commands}\n\n{MONGO_NOTE}")
		return 0

	cwd = str(folder)

	def check(command, what):
		if run(command, cwd)[0] != 0:
			raise DeployError(f"{what} failed (`{' '.join(command[1:3])} ...`); see its output above")

	if run([fly, "auth", "whoami"], cwd, capture=True)[0] != 0:
		check([fly, "auth", "login"], "Logging in to Fly.io")

	if run([fly, "status", "--app", app], cwd, capture=True)[0] != 0:
		say(f'Creating the Fly.io app "{app}"')
		check([fly, "launch", "--no-deploy", "--copy-config"], "fly launch")
		existing = set()
	else:
		# Set once and kept: a new secret key would sign everyone out on each deploy
		code, output = run([fly, "secrets", "list", "--app", app], cwd, capture=True)
		if code != 0:
			raise DeployError(f"Couldn't list the secrets of the Fly.io app {app}:\n{output.strip()}")
		existing = set(re.findall(r"^\s*([A-Z][A-Z0-9_]*)\s", output, re.MULTILINE))

	values = {}
	if environ.get("DOMINO_SECRET_KEY"):
		values["DOMINO_SECRET_KEY"] = environ["DOMINO_SECRET_KEY"]
	elif "DOMINO_SECRET_KEY" not in existing:
		values["DOMINO_SECRET_KEY"] = new_secret_key()

	if not mongo and "DOMINO_MONGO__URL" not in existing and not committed_mongo_url(folder) and uses_collections(folder):
		mongo = prompt("MongoDB URL for production (mongodb+srv://..., blank to skip): ")
	if mongo:
		values["DOMINO_MONGO__URL"] = mongo

	check_app(folder, mongo or "DOMINO_MONGO__URL" in existing)

	if values:
		say(f"Setting Fly.io secrets: {', '.join(values)}")
		check([fly, "secrets", "set", "--app", app, "--stage"] + [f"{key}={value}" for key, value in values.items()], "fly secrets set")

	# One machine: a page lives in the memory of the machine that made it, and Fly's proxy
	# would spread its requests across several
	check([fly, "deploy", "--app", app, "--ha=false"], "fly deploy")

	say(f"\nDeployed: https://{app}.fly.dev/")

	return 0


# domino deploy render


def git_root(folder):

	for parent in [folder] + list(folder.parents):
		if (parent / ".git").exists():
			return parent

	return None


def deploy_render(path, name=None, mongo_url=None, force=False, environ=None):

	folder = build(path, force)

	# Render reads paths from the repository's root, and the Blueprint from render.yaml there
	# unless told another path
	root = git_root(folder) or folder
	relative = folder.relative_to(root).as_posix()
	paths = ""
	if relative != ".":
		paths = f"    rootDir: {relative}\n    dockerContext: ./{relative}\n    dockerfilePath: ./{relative}/Dockerfile\n"

	app = slug(name or folder.name)
	write_file(folder / "render.yaml", RENDER_TEMPLATE.format(name=app, port=PORT, health=HEALTH_PATH, paths=paths, proxies=PLATFORM_PROXIES), force)
	say()

	mongo, source = find_mongo_url(folder, mongo_url, environ)
	check_app(folder, mongo, " Render asks for it when you create the Blueprint (step 3).")

	files = "Dockerfile .dockerignore requirements.txt render.yaml"
	blueprint = "" if relative == "." else f"\n   Set its Blueprint path to {relative}/render.yaml."
	value = f"the URL from {source}" if mongo else "your MongoDB URL (mongodb+srv://...)"

	say("Render deploys Blueprints from its dashboard, so the rest happens there:\n\n"
		"1. Commit these files and push the repository to GitHub (or GitLab or Bitbucket):\n\n"
		f"    git add {files}\n"
		'    git commit -m "Deploy to Render"\n'
		"    git push\n\n"
		f"2. In the Render dashboard, choose New > Blueprint and pick the repository: {RENDER_BLUEPRINTS_URL}{blueprint}\n"
		f"3. Render asks for DOMINO_MONGO__URL: enter {value}.\n"
		"   It makes DOMINO_SECRET_KEY itself. If the app sends email (password resets), add\n"
		f"   DOMINO_PUBLIC_URL with the app's address (https://{app}.onrender.com, or your domain).\n"
		"4. Apply it. Each push to the branch deploys again.\n\n"
		f"Render keeps the app on one instance; don't scale it to more, since a page lives in the memory of the\n"
		f"instance that made it.\n\n{MONGO_NOTE}")

	return 0


# domino deploy docker


def docker_available(docker):

	return docker is not None and run([docker, "info"], capture=True)[0] == 0


def deploy_docker(path, name=None, mongo_url=None, force=False, environ=None):

	folder = build(path, force)
	image = slug(name or folder.name)
	write_file(folder / "docker-compose.yml", COMPOSE_TEMPLATE.format(name=image, port=PORT, database=image.replace("-", "_")), force)
	say()

	mongo, source = find_mongo_url(folder, mongo_url, environ)
	check_app(folder, mongo, " (docker-compose.yml runs a MongoDB of its own; `docker run` needs one)")

	docker = shutil.which("docker")
	if docker_available(docker):
		say(f"Building the image {image}")
		if run([docker, "build", "-t", image, "."], str(folder))[0] != 0:
			raise DeployError("docker build failed; see its output above")
		say()
	else:
		reason = "isn't running" if docker else "isn't installed (https://docs.docker.com/get-docker/)"
		say(f"Docker {reason}. Build the image with:\n\n    docker build -t {image} {shell_quote(folder)}\n")

	mongo_value = shlex.quote(mongo) if mongo else "'mongodb+srv://...'"
	say("Run it, with your MongoDB:\n\n"
		f"    export DOMINO_SECRET_KEY={new_secret_key()}\n"
		f"    export DOMINO_MONGO__URL={mongo_value}\n"
		f"    docker run -p {PORT}:{PORT} -e DOMINO_SECRET_KEY -e DOMINO_MONGO__URL {image}\n\n"
		f"Over plain HTTP (http://localhost:{PORT}) add -e DOMINO_DOMINO__SECURE_COOKIES=false, or logins won't stick;\n"
		"-e WEB_CONCURRENCY=2 sets the number of worker processes. Keep the same secret key between runs.\n\n"
		"Or run it with a MongoDB of its own (a single-node replica set, data in a Docker volume):\n\n"
		f"    cd {shell_quote(folder)}\n"
		"    export DOMINO_SECRET_KEY=...   (as above)\n"
		"    docker compose up -d\n\n"
		f"{MONGO_NOTE}")

	return 0


PLATFORMS = {
	"fly": deploy_fly,
	"render": deploy_render,
	"docker": deploy_docker,
}


def deploy(platform, path, name=None, mongo_url=None, force=False):

	return PLATFORMS[platform](path, name=name, mongo_url=mongo_url, force=force)
