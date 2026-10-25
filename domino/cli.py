"""The `domino` command: `domino run` and `domino create`, like `meteor run` and `meteor create`."""

import argparse
import importlib.util
import json
import os
import re
import sys
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path

from . import devmongo


APP_TEMPLATE = '''\
import time

import domino.tags as t
from domino import Collection, Domino
from domino.components import Document


app = Domino(__name__)

# Shared by every open page: inserting a task re-renders them all
tasks = Collection("tasks")


class Tasks(t.div):


	def render(self):

		self([
			form := t.form() [
				t.input(name="text", placeholder="What needs doing?", required=True, autocomplete="off"),
				t.button(type="submit") [
					"Add"
				]
			],
			t.ul()([
				t.li() [
					task["text"]
				]
				for task in tasks.find(sort=[("created", -1)])
			])
		])

		form.bind("submit", self.add)


	def add(self, event):

		tasks.insert({"text": event.form.get("text", "").strip()[:200], "created": time.time()})

		return self


@app.route("/")
def index():

	return Document(title=app.settings.public.title) [
		t.h1() [
			app.settings.public.title
		],
		Tasks()
	]


if __name__ == "__main__":
	app.run(debug=True)
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
	run.add_argument("app", nargs="?", default="app.py", help="the app's Python file (default: app.py)")
	run.add_argument("--port", type=int, default=5000, help="port to serve on (default: 5000); MongoDB uses the next one")
	run.add_argument("--host", default="127.0.0.1", help="interface to serve on (default: 127.0.0.1)")
	run.add_argument("--no-mongo", action="store_true", help="don't start a local MongoDB")
	run.add_argument("--mongo-version", help=f"MongoDB release series to download (default: {devmongo.DEFAULT_VERSION})")

	create = commands.add_parser("create", help="create a new app folder")
	create.add_argument("name", help="folder to create")

	return parser


def main(argv=None):

	parser = build_parser()
	args = parser.parse_args(argv)

	try:
		if args.command == "run":
			return run(args)
		if args.command == "create":
			return create(args.name)
	except (CliError, devmongo.DevMongoError) as error:
		print(f"domino: {error}", file=sys.stderr)
		return 1

	parser.print_help()
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
		raise CliError(f"No app at {path} (pass the app's Python file, e.g. `domino run app.py`)")

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


def run(args):

	path = Path(args.app).resolve()

	if args.no_mongo:
		os.environ[devmongo.ENV_DISABLE] = "1"

	# Read as the setting mongo.version. A JSON string, so 7.10 isn't read as the number 7.1
	if args.mongo_version:
		os.environ["DOMINO_MONGO__VERSION"] = json.dumps(args.mongo_version)

	app = find_app(load_module(path))

	# The reloader runs this again in a child process, which shouldn't repeat it
	if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
		print(f"domino: App: http://{args.host}:{args.port}/", file=sys.stderr, flush=True)

	# Domino.run() starts the local MongoDB, once, outside the reloader's child process
	app.run(host=args.host, port=args.port, debug=True, threaded=True)

	return 0


def create(name):

	folder = Path(name)

	if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
		raise CliError(f"{folder} already exists and isn't empty")

	folder.mkdir(parents=True, exist_ok=True)

	title = folder.resolve().name
	settings = {"public": {"title": title}}

	(folder / "app.py").write_text(APP_TEMPLATE, encoding="utf-8")
	(folder / "settings.json").write_text(json.dumps(settings, indent=4) + "\n", encoding="utf-8")
	(folder / ".gitignore").write_text(GITIGNORE_TEMPLATE, encoding="utf-8")

	print(f"Created {folder}/\n\nTo run it:\n\n    cd {name}\n    domino run\n")

	return 0
