"""The `domino` command: `domino run` and `domino create`, like `meteor run` and `meteor create`,
`domino serve` for production, `domino build` and `domino deploy`, like `meteor deploy`, and
`domino tailwind build` before deploying."""

import argparse
import html
import importlib.util
import json
import os
import re
import sys
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path

from . import deploy, devmongo, tailwind


APP_TEMPLATE = '''\
from domino import Domino


# Every file in pages/ is a page: pages/index.py is /, pages/about.py would be /about
app = Domino(__name__)


if __name__ == "__main__":
	app.run(debug=True)
'''

# "{title}" is replaced with the app's name
LAYOUT_TEMPLATE = '''\
<!-- Wraps every page in this folder and below: the page goes where <slot /> is.
     Domino adds the doctype, its script and the components' CSS -->
<html lang="en">
	<head>
		<meta charset="utf-8">
		<meta name="viewport" content="width=device-width, initial-scale=1">
		<title>{title}</title>
	</head>
	<body>
		<h1>{title}</h1>
		<slot />
	</body>
</html>
'''

INDEX_TEMPLATE = '''\
from components.tasks import Tasks


# This file is the page at /
def page():

	return Tasks()
'''

COMPONENT_TEMPLATE = '''\
import time

import domino.tags as t

from data import tasks


# Logic in Python, markup in tasks.html next to this file: <TaskForm>, <TaskList> and <NoTasks>
# there are the markup of the classes of those names. Tasks only composes, so it has a render()
class Tasks(t.div):


	def render(self):

		# Reading the collection here re-renders this on every open page when it changes
		found = tasks.find(sort=[("created", -1)]).fetch()

		return [
			TaskForm(on_add=self.add),
			TaskList(tasks=found) if found else NoTasks(),
		]


	def add(self, text):

		tasks.insert({"text": text[:200], "created": time.time()})


class TaskForm(t.form):

	on_add = None  # a prop: the parent's handler, called with the text


	def submit(self, event):

		text = event.form.get("text", "").strip()
		if text:
			self.on_add(text)


class TaskList(t.div):

	tasks = None  # a prop: the tasks to show


class NoTasks(t.p):

	pass
'''

COMPONENT_HTML_TEMPLATE = '''\
<!-- The markup of the components in tasks.py: each top-level tag is the class of that name -->

<TaskForm on-submit="submit">
	<input name="text" placeholder="What needs doing?" required autocomplete="off">
	<button type="submit">Add</button>
</TaskForm>

<TaskList>
	<ul>
		<li each="task in tasks">{{ task.text }}</li>
	</ul>
</TaskList>

<NoTasks>Nothing to do yet.</NoTasks>
'''

DATA_TEMPLATE = '''\
from domino import Collection


# Stored in MongoDB and shared by every open page
tasks = Collection("tasks")
'''

INDEX_TEST_TEMPLATE = '''\
# Tests for pages/index.py, run with `pytest`. `page` is the page, open in a simulated browser.
# Each test gets an empty database, on a MongoDB started for the tests


def test_add_a_task(page):

	page.fill("input[name=text]", "Buy milk")
	page.click("button", text="Add")

	assert page.text("ul") == "Buy milk"
	assert page.value("input[name=text]") == ""


def test_other_tabs_see_it(page, open_page):

	other = open_page()

	page.fill("input[name=text]", "Walk the dog")
	page.click("button", text="Add")
	other.sync()

	assert other.text("ul") == "Walk the dog"
'''

# `domino create --tailwind`: the same app, styled with Tailwind CSS classes
TAILWIND_LAYOUT_TEMPLATE = '''\
<!-- Wraps every page in this folder and below: the page goes where <slot /> is. Tailwind CSS
     classes work anywhere ("tailwind": true in settings.json), built into the CSS every page links -->
<html lang="en">
	<head>
		<meta charset="utf-8">
		<meta name="viewport" content="width=device-width, initial-scale=1">
		<title>{title}</title>
	</head>
	<body class="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
		<main class="mx-auto max-w-xl px-6 py-12">
			<h1 class="mb-6 text-3xl font-bold tracking-tight">{title}</h1>
			<slot />
		</main>
	</body>
</html>
'''

# The Python side is the same (components/tasks.py); the markup has Tailwind classes
TAILWIND_COMPONENT_HTML_TEMPLATE = '''\
<!-- The markup of the components in tasks.py: each top-level tag is the class of that name -->

<TaskForm class="flex gap-2" on-submit="submit">
	<input name="text" placeholder="What needs doing?" required autocomplete="off"
		class="flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-900">
	<button type="submit" class="rounded-lg bg-indigo-600 px-4 py-2 font-medium text-white hover:bg-indigo-500">Add</button>
</TaskForm>

<TaskList>
	<ul class="mt-4 space-y-2">
		<li each="task in tasks" class="rounded-lg bg-white px-3 py-2 shadow-sm dark:bg-slate-900">{{ task.text }}</li>
	</ul>
</TaskList>

<NoTasks class="mt-4 text-slate-500">Nothing to do yet.</NoTasks>
'''

GITIGNORE_TEMPLATE = '''\
settings.local.json
.domino/
__pycache__/
'''


def get_version():

	try:
		return package_version("domino-web")
	except PackageNotFoundError:
		return "unknown"


def build_parser():

	parser = argparse.ArgumentParser(prog="domino", description="Domino, an experimental Python web framework built on Flask.")
	parser.add_argument("--version", action="version", version=f"domino {get_version()}")
	commands = parser.add_subparsers(dest="command", metavar="command")

	run = commands.add_parser("run", help="run an app in development, with a local MongoDB")
	run.add_argument("app", nargs="?", default=".", help="the app's folder or Python file (default: the current folder)")
	run.add_argument("--port", type=int, default=5000, help="port to serve on (default: 5000); MongoDB uses the next one")
	run.add_argument("--host", default="127.0.0.1", help="interface to serve on (default: 127.0.0.1)")
	run.add_argument("--no-mongo", action="store_true", help="don't start a local MongoDB")
	run.add_argument("--mongo-version", help=f"MongoDB release series to download (default: {devmongo.DEFAULT_VERSION})")

	serve = commands.add_parser("serve", help="serve an app in production, on every CPU core")
	serve.add_argument("app", nargs="?", default=".", help="the app's folder or Python file (default: the current folder)")
	serve.add_argument("--workers", type=positive_int, help="processes to serve with (default: one per CPU core)")
	serve.add_argument("--port", type=int, default=8000, help="port to serve on (default: 8000)")
	serve.add_argument("--host", default="127.0.0.1", help="interface to serve on (default: 127.0.0.1; 0.0.0.0 for every one)")

	build = commands.add_parser("build", help="write a Dockerfile for an app, to deploy it anywhere")
	build.add_argument("app", nargs="?", default=".", help="the app's folder (default: the current folder)")
	build.add_argument("--force", action="store_true", help="write the files again even if they're there")

	ship = commands.add_parser("deploy", help="deploy an app to Fly.io or Render, or as a Docker image")
	ship.add_argument("platform", choices=sorted(deploy.PLATFORMS), help="where to deploy: fly, render or docker")
	ship.add_argument("app", nargs="?", default=".", help="the app's folder (default: the current folder)")
	ship.add_argument("--name", help="the app's name on the platform (default: from the folder's name)")
	ship.add_argument("--mongo-url", help="the production MongoDB URL (default: DOMINO_MONGO__URL, MONGO_URL or settings.local.json)")
	ship.add_argument("--force", action="store_true", help="write the deployment files again even if they're there")

	create = commands.add_parser("create", help="create a new app folder")
	create.add_argument("name", help="folder to create")
	create.add_argument("--tailwind", action="store_true", help="style it with Tailwind CSS")

	tailwind_parser = commands.add_parser("tailwind", help="Tailwind CSS: `domino tailwind build` before deploying")
	tailwind_parser.set_defaults(usage=tailwind_parser)
	tailwind_commands = tailwind_parser.add_subparsers(dest="tailwind_command", metavar="command")
	tailwind_build = tailwind_commands.add_parser("build", help="build an app's minified Tailwind CSS into .domino/tailwind.css (e.g. in a Dockerfile)")
	tailwind_build.add_argument("app", nargs="?", default=".", help="the app's folder or Python file (default: the current folder)")

	return parser


def positive_int(value):

	number = int(value)
	if number < 1:
		raise argparse.ArgumentTypeError(f"must be at least 1, not {value}")

	return number


def main(argv=None):

	parser = build_parser()
	args = parser.parse_args(argv)

	try:
		if args.command == "run":
			return run(args)
		if args.command == "serve":
			return serve(args)
		if args.command == "create":
			return create(args.name, args.tailwind)
		if args.command == "build":
			deploy.build(args.app, args.force)
			return 0
		if args.command == "deploy":
			return deploy.deploy(args.platform, args.app, name=args.name, mongo_url=args.mongo_url, force=args.force)
		if args.command == "tailwind" and args.tailwind_command == "build":
			return tailwind_build(args)
	except (CliError, devmongo.DevMongoError, deploy.DeployError, tailwind.TailwindError) as error:
		print(f"domino: {error}", file=sys.stderr)
		return 1

	# `domino` or `domino tailwind` alone
	getattr(args, "usage", parser).print_help()
	return 2


class CliError(Exception):
	"""A problem worth one line on stderr, not a traceback."""


def module_name(path):

	# Stable, so the reloader's child process registers the app under the same name
	name = re.sub(r"\W", "_", Path(path).stem)

	return f"domino_app_{name}"


def load_module(path):

	path = Path(path).resolve()
	if not path.is_file():
		raise CliError(f"No app at {path} (pass the app's folder or Python file, e.g. `domino run app.py`)")

	# Like `python app.py`: the app's own folder comes first on the import path
	sys.path.insert(0, str(path.parent))

	name = module_name(path)
	spec = importlib.util.spec_from_file_location(name, path)
	module = importlib.util.module_from_spec(spec)
	# Flask finds the app's folder (for settings.json and static files) through sys.modules
	sys.modules[name] = module
	spec.loader.exec_module(module)

	return module


def find_app(module):

	from .core import Domino

	if isinstance(getattr(module, "app", None), Domino):
		return module.app

	for value in vars(module).values():
		if isinstance(value, Domino):
			return value

	raise CliError(f"No Domino app in {module.__file__} (create one with `app = Domino(__name__)`)")


def load_app(path):
	"""The app in a Python file, or in a folder: its app.py, or else one made for its pages/."""

	from .core import Domino

	path = Path(path).resolve()
	if not path.is_dir():
		return find_app(load_module(path))

	if (path / "app.py").is_file():
		return find_app(load_module(path / "app.py"))

	if not (path / "pages").is_dir():
		raise CliError(f"No app.py or pages/ folder in {path}")

	# No boilerplate needed: an app rooted at the folder, serving its pages/. Remembered so
	# the reloader's new process can make it again (see domino.asgi.app_location)
	app = Domino(module_name(path), root_path=str(path))
	app.domino_folder = str(path)

	return app


def run(args):

	if args.no_mongo:
		os.environ[devmongo.ENV_DISABLE] = "1"

	# Read as the setting mongo.version. A JSON string, so 7.10 isn't read as the number 7.1
	if args.mongo_version:
		os.environ["DOMINO_MONGO__VERSION"] = json.dumps(args.mongo_version)

	app = load_app(args.app)

	# The reloader runs this again in a child process, which shouldn't repeat it. With --port 0
	# the server says which port it picked
	if os.environ.get("WERKZEUG_RUN_MAIN") != "true" and args.port:
		print(f"domino: App: http://{args.host}:{args.port}/", file=sys.stderr, flush=True)

	# Domino.run() starts the local MongoDB, once, outside the reloader's child process
	app.run(host=args.host, port=args.port, debug=True)

	return 0


def app_path(path):
	"""The app's folder or file, checked like load_app() does but without importing it."""

	path = Path(path).resolve()
	if path.is_dir() and not (path / "app.py").is_file() and not (path / "pages").is_dir():
		raise CliError(f"No app.py or pages/ folder in {path}")
	if not path.exists():
		raise CliError(f"No app at {path} (pass the app's folder or Python file, e.g. `domino serve app.py`)")

	return str(path)


def env_workers():
	"""The number of workers in WEB_CONCURRENCY, as uvicorn and gunicorn read it (platforms and
	the Dockerfile `domino build` writes set it), or None."""

	value = os.environ.get("WEB_CONCURRENCY", "").strip()
	if not value:
		return None

	try:
		return positive_int(value)
	except (ValueError, argparse.ArgumentTypeError):
		raise CliError(f"WEB_CONCURRENCY must be a number of workers, at least 1, not {value!r}") from None


def serve(args):

	from . import asgi, workers

	count = args.workers or env_workers() or workers.default_count()

	# One process needs no router: the app served by uvicorn, as `uvicorn app:app.asgi` would
	if count == 1:
		app = load_app(args.app)
		tailwind.prepare(app.root_path, app.tailwind)
		print(f"domino: App: http://{args.host}:{args.port}/ (1 worker)", file=sys.stderr, flush=True)
		asgi.serve(app, args.host, args.port, False)
		return 0

	# The workers load the app themselves; this process only routes (and builds the CSS they serve)
	path = app_path(args.app)
	tailwind.prepare(*app_tailwind(path))

	return workers.serve(path, args.host, args.port, count)


def app_tailwind(path):
	"""The app's folder and how it uses Tailwind, from its settings, without importing it."""

	from .settings import load_settings

	path = Path(path).resolve()
	root = path if path.is_dir() else path.parent

	return root, tailwind.options(load_settings(str(root)), root)


def tailwind_build(args):

	root, options = app_tailwind(app_path(args.app))
	if options is None:
		raise CliError(f'{root} doesn\'t use Tailwind CSS: add {{"tailwind": true}} to its settings.json, or a tailwind.css')

	output = tailwind.build(root, options, minify=True)
	print(f"domino: Tailwind CSS: built {output} ({output.stat().st_size // 1024} KB)", file=sys.stderr, flush=True)

	return 0


def create(name, with_tailwind=False):

	folder = Path(name)

	if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
		raise CliError(f"{folder} already exists and isn't empty")

	folder.mkdir(parents=True, exist_ok=True)

	title = folder.resolve().name
	settings = {"public": {"title": title}}
	if with_tailwind:
		settings["tailwind"] = True

	files = {
		"app.py": APP_TEMPLATE,
		"pages/layout.html": (TAILWIND_LAYOUT_TEMPLATE if with_tailwind else LAYOUT_TEMPLATE).replace("{title}", html.escape(title)),
		"pages/index.py": INDEX_TEMPLATE,
		"pages/index_test.py": INDEX_TEST_TEMPLATE,
		"components/tasks.py": COMPONENT_TEMPLATE,
		"components/tasks.html": TAILWIND_COMPONENT_HTML_TEMPLATE if with_tailwind else COMPONENT_HTML_TEMPLATE,
		"data.py": DATA_TEMPLATE,
		"settings.json": json.dumps(settings, indent=4) + "\n",
		".gitignore": GITIGNORE_TEMPLATE,
	}

	for path, text in files.items():
		(folder / path).parent.mkdir(parents=True, exist_ok=True)
		(folder / path).write_text(text, encoding="utf-8")

	print(f"Created {folder}/\n\nTo run it:\n\n    cd {name}\n    domino run\n\nTo test it:\n\n    pytest\n\nTo deploy it (to Fly.io, Render, or anywhere Docker runs):\n\n    domino deploy fly\n")

	return 0
