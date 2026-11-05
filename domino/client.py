"""Client components (experimental): components that run in the browser, in Python.

A component with `client = True` is rendered by the server once, so the page works before
anything else loads, and then runs in the browser on a small Python runtime (MicroPython compiled
to WebAssembly, or Pyodide): its handlers and re-renders happen there, with no round trip, and keep
working offline. It's the same API: State, render() returning tags, on_<event>= handlers, class-level
css (still written by the server). See docs/research/client-python.md.

The component's whole module is sent to the browser, so it may only import what exists there:
domino.tags, State from domino, and a few standard modules (ALLOWED_MODULES). That's checked when
the module is imported, so a mistake stops the app at startup. Code in it is public: never put
server-only code or secrets in a client component's module.

The browser gets, from this app: /_domino/client/loader.js (domino/client.js with its settings),
/_domino/client/module/<module>.py (the modules of client components, nothing else) and, with
the "local" runtime, /_domino/client/runtime/<file> (the runtime, downloaded once from npm into
~/.domino/client-runtime).
"""

import ast
import base64
import builtins
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.request
from pathlib import Path

from flask import Response, abort, request, send_from_directory

from . import devmongo, optimistic
from .util import urlopen


HERE = Path(__file__).parent
SHIM = HERE / "client_shim"

# The Python runtimes the browser can use, pinned to a version and its npm tarball's checksum
RUNTIMES = {
	"micropython": {
		"package": "@micropython/micropython-webassembly-pyscript",
		"version": "1.29.0-6",
		"integrity": "sha512-kLwGPJFsLY/2aUPmzZxpvauFSmKc0SlJWVvvEttULR0poVQ6W9HV//1fUJyxrGWAxCVDw9aYqJ0LAog0ZLjYVA==",
		"files": ["micropython.mjs", "micropython.wasm"],
	},
	"pyodide": {
		"package": "pyodide",
		"version": "314.0.7",
		"integrity": "sha512-0YvXxEhfEdpLfb/XkM2BFAeMROq0iMUX2bzzH9pOttyMcWkwq+HbE5uyuGD82LN7y2q+SNvi/6V5JEsOlD2R1A==",
		"files": ["pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"],
	},
}

REGISTRY_URL = "https://registry.npmjs.org"
CDN_URL = "https://cdn.jsdelivr.net/npm"

# What a client component's module may import: these exist in the browser's Python
ALLOWED_MODULES = {"math", "random", "time", "json"}
ALLOWED_FROM_DOMINO = {"State", "tags"}

# Why some of what the server has can't be used, for the error message
HINTS = {
	"Collection": "Collections live on the server; pass the data in as State, or send it to the server with self.emit()",
	"accounts": "accounts live on the server; render what the user should see in a server component around this one",
	"batch": "reactive data lives on the server",
	"html": "template strings aren't supported in client components yet; use tags",
}

MODULE_ROUTE = "/_domino/client/module/"
RUNTIME_ROUTE = "/_domino/client/runtime/"


class ClientComponentError(Exception):
	"""A client component can't be sent to the browser (see the message)."""


class ClientModule:
	"""A module with client components, as it's sent to the browser."""


	def __init__(self, name, path, source):

		self.name = name
		self.path = path
		self.source = source
		self.hash = hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]
		self.key = f"{name}@{self.hash}"  # how the browser and the shim know it
		self.classes = []


# Module name -> ClientModule, and client component class -> its ClientModule
modules = {}
classes = {}

_lock = threading.Lock()

# The shim keeps what the render running now binds in module globals, as the browser has one
# thread; on the server, renders take turns
_render_lock = threading.RLock()


def register(cls):
	"""Called for each class with `client = True` when it's defined: check that its module can run
	in the browser, and remember it. Raises ClientComponentError otherwise."""

	module = check_module(cls)

	if getattr(cls, "live", False) is True:
		raise ClientComponentError(f"{cls.__name__}: client components run in the browser and can't be live")

	for name in sorted(optimistic.state_names(cls)):
		value = getattr(cls, name)._value
		try:
			json.dumps(value)
		except (TypeError, ValueError):
			raise ClientComponentError(
				f"{cls.__name__}.{name}: State(...) of a client component must hold JSON values "
				f"(numbers, strings, lists, dicts, True/False/None), not {value!r}"
			) from None

	with _lock:
		if cls.__name__ not in module.classes:
			module.classes.append(cls.__name__)
		classes[cls] = module


def check_module(cls):

	name = cls.__module__
	module = sys.modules.get(name)
	path = getattr(module, "__file__", None)
	if not path or not os.path.isfile(path):
		raise ClientComponentError(f"{cls.__name__} has client = True, but its source file can't be found to send to the browser")

	source = Path(path).read_text(encoding="utf-8")
	with _lock:
		known = modules.get(name)
		if known is not None and known.path == path and known.source == source:
			return known

	label = f"{cls.__name__} has client = True, so all of {display_path(path)} is sent to the browser"
	tree = ast.parse(source, path)
	for node in ast.walk(tree):
		problem = None
		if isinstance(node, ast.Import):
			for alias in node.names:
				if alias.name not in ALLOWED_MODULES and alias.name != "domino.tags":
					problem = f"it can't import {alias.name}"
		elif isinstance(node, ast.ImportFrom):
			if node.level:
				problem = "it can't use relative imports"
			elif node.module == "domino":
				for alias in node.names:
					if alias.name not in ALLOWED_FROM_DOMINO:
						problem = f"it can't import {alias.name} from domino"
						if alias.name in HINTS:
							problem += f": {HINTS[alias.name]}"
			elif node.module != "domino.tags" and node.module not in ALLOWED_MODULES:
				problem = f"it can't import from {node.module}"
		if problem:
			allowed = ", ".join(sorted(ALLOWED_MODULES))
			raise ClientComponentError(
				f"{path}:{node.lineno}: {label}, and {problem}. In the browser there are only domino.tags, "
				f"State (from domino) and the modules {allowed}. Keep server code in another module."
			)

	module = ClientModule(name, path, source)
	with _lock:
		modules[name] = module

	return module


# Rendering on the server: the browser's code, run here, so both make the same HTML

_shim = None


def shim():
	"""The browser's `domino` package (domino/client_shim/domino), loaded in CPython under another
	name, so the server renders client components with the same code the browser runs."""

	global _shim

	with _lock:
		if _shim is None:
			folder = SHIM / "domino"
			spec = importlib.util.spec_from_file_location(
				"_domino_client_shim", folder / "__init__.py", submodule_search_locations=[str(folder)]
			)
			package = importlib.util.module_from_spec(spec)
			sys.modules[spec.name] = package
			spec.loader.exec_module(package)
			_shim = package

	return _shim


def shim_builtins(package):
	"""Builtins for running a client module on the server, where `import domino` means the shim."""

	original = builtins.__import__

	def import_(name, globals=None, locals=None, fromlist=(), level=0):
		if level == 0 and name == "domino.tags" and fromlist:
			return package.tags
		if level == 0 and (name == "domino" or name.startswith("domino.")):
			return package
		return original(name, globals, locals, fromlist, level)

	return dict(vars(builtins), __import__=import_)


def render(element, level, indent, styles):
	"""A client component's HTML for the page: rendered by the shim, with its State values and
	attributes in data-domino-state for the browser to take over from."""

	cls = type(element)
	module = classes[cls]
	package = shim()

	with _lock:
		if module.key not in package.modules:
			package.load_module(module.key, module.source, shim_builtins(package), module.path)

	# Class-level css is still the server's: written into the page once, base classes first
	styled = [base for base in cls.__mro__ if "css" in base.__dict__ and base.__module__ != "domino.tags"]
	for base in reversed(styled):
		styles.add(base)

	state = {name: getattr(cls, name)._of(element)._value for name in sorted(optimistic.state_names(cls))}
	attrs = {}
	for key, value in element.__attributes__.items():
		if key == "id" or key.startswith("_"):
			continue
		try:
			json.dumps(value)
		except (TypeError, ValueError):
			raise ClientComponentError(f"{cls.__name__}({key}={value!r}): only JSON values can be sent to the browser") from None
		attrs[key] = value

	with _render_lock:
		html = package.render(element.id(), module.key, cls.__name__, {"state": state, "attrs": attrs})

	if isinstance(indent, int):
		indent = " " * indent

	return f"{indent * level}{html}{'' if indent == '' else chr(10)}"


# What the browser loads


def runtime_name(app):

	name = app.config.get("DOMINO_CLIENT_PYTHON") or "micropython"
	if name not in RUNTIMES:
		raise ClientComponentError(f'Unknown client Python {name!r}: use one of {", ".join(RUNTIMES)}')

	return name


def runtime_url(app):
	"""Where the browser gets the runtime: the client_runtime setting, a URL (ending in /) or "local"
	(served by this app from the cache, see ensure_runtime). By default "local" while debugging and
	jsDelivr otherwise."""

	setting = app.config.get("DOMINO_CLIENT_RUNTIME")
	if not setting:
		setting = "local" if app.debug else "cdn"

	runtime = RUNTIMES[runtime_name(app)]
	if setting == "local":
		return RUNTIME_ROUTE
	if setting == "cdn":
		return f"{CDN_URL}/{runtime['package']}@{runtime['version']}/"

	return setting if setting.endswith("/") else setting + "/"


def shim_sources():

	return {
		"domino/__init__.py": (SHIM / "domino" / "__init__.py").read_text(encoding="utf-8"),
		"domino/tags.py": (SHIM / "domino" / "tags.py").read_text(encoding="utf-8"),
	}


def loader_js(app):

	config = {
		"python": runtime_name(app),
		"url": runtime_url(app),
		"modules": MODULE_ROUTE,
		"heapsize": int(app.config.get("DOMINO_CLIENT_HEAP_MB") or 16) * 1024 * 1024,
		"shim": shim_sources(),
	}
	script = (HERE / "client.js").read_text(encoding="utf-8")

	# JSON is a JavaScript expression; "</" can't end anything in a module script, but escape it anyway
	return f"const CONFIG = {json.dumps(config).replace('</', '<' + chr(92) + '/')};\n{script}"


def add_routes(app):

	def loader():
		return Response(loader_js(app), mimetype="text/javascript", headers={"Cache-Control": "no-cache"})

	def module_source(name):
		# Only modules of client components, which were checked when they were imported
		module = modules.get(name)
		if module is None or not module.classes:
			abort(404)
		headers = {"Cache-Control": "no-cache"}
		if request.args.get("v") == module.hash:
			headers = {"Cache-Control": "public, max-age=31536000, immutable"}
		return Response(module.source, mimetype="text/x-python", headers=headers)

	def runtime_file(filename):
		if runtime_url(app) != RUNTIME_ROUTE:
			abort(404)
		name = runtime_name(app)
		if filename not in RUNTIMES[name]["files"]:
			abort(404)
		folder = ensure_runtime(name)
		mimetype = "application/wasm" if filename.endswith(".wasm") else None
		if filename.endswith((".mjs", ".js")):
			mimetype = "text/javascript"
		return send_from_directory(folder, filename, mimetype=mimetype, max_age=3600)

	app.add_url_rule("/_domino/client/loader.js", "domino_client_loader", loader, methods=["GET"])
	app.add_url_rule(MODULE_ROUTE + "<name>.py", "domino_client_module", module_source, methods=["GET"])
	app.add_url_rule(RUNTIME_ROUTE + "<filename>", "domino_client_runtime", runtime_file, methods=["GET"])


# The runtime for "local": the npm package, downloaded once into ~/.domino/client-runtime


def runtime_folder(name, environ=None):

	runtime = RUNTIMES[name]
	package = runtime["package"].rsplit("/", 1)[-1]

	return devmongo.domino_home(environ) / "client-runtime" / f"{package}@{runtime['version']}"


def ensure_runtime(name="micropython", environ=None):
	"""The folder with the runtime's files, downloading its npm package the first time (from the npm
	registry, or with `npm pack` when that fails), checked against its pinned sha512."""

	runtime = RUNTIMES[name]
	folder = runtime_folder(name, environ)
	if all((folder / file).is_file() for file in runtime["files"]):
		return folder

	with devmongo.file_lock(folder.parent / f"{folder.name}.lock"):
		if all((folder / file).is_file() for file in runtime["files"]):
			return folder

		folder.parent.mkdir(parents=True, exist_ok=True)
		with tempfile.TemporaryDirectory(dir=folder.parent, prefix=".download-") as temp:
			tarball = download_package(runtime, Path(temp))
			check_integrity(tarball, runtime["integrity"])
			unpacked = Path(temp) / "unpacked"
			unpacked.mkdir()
			with tarfile.open(tarball, "r:gz") as archive:
				for file in runtime["files"]:
					member = archive.getmember(f"package/{file}")
					with archive.extractfile(member) as source, open(unpacked / file, "wb") as out:
						shutil.copyfileobj(source, out)
			if folder.exists():
				shutil.rmtree(folder)
			os.replace(unpacked, folder)

	return folder


def download_package(runtime, folder):

	package, version = runtime["package"], runtime["version"]
	tarball = folder / "package.tgz"
	url = f"{REGISTRY_URL}/{package}/-/{package.rsplit('/', 1)[-1]}-{version}.tgz"

	devmongo.log(f"Downloading {package}@{version} for client components from {url}")
	try:
		with urlopen(url, timeout=120) as response, open(tarball, "wb") as out:
			shutil.copyfileobj(response, out)
		return tarball
	except OSError as error:
		tarball.unlink(missing_ok=True)
		npm = shutil.which("npm")
		if not npm:
			raise ClientComponentError(f"Couldn't download {url}: {error}") from error

	# npm may know a proxy or a mirror that plain urllib doesn't
	devmongo.log(f"Download failed; trying npm pack {package}@{version}")
	result = subprocess.run(
		[npm, "pack", f"{package}@{version}", "--pack-destination", str(folder), "--silent"],
		capture_output=True, text=True, timeout=300,
	)
	packed = [path for path in folder.glob("*.tgz")]
	if result.returncode != 0 or not packed:
		raise ClientComponentError(f"npm pack {package}@{version} failed: {result.stderr.strip()}")

	return packed[0]


def check_integrity(path, integrity):

	algorithm, expected = integrity.split("-", 1)
	digest = hashlib.new(algorithm)
	with open(path, "rb") as source:
		for chunk in iter(lambda: source.read(1 << 20), b""):
			digest.update(chunk)

	if base64.b64encode(digest.digest()).decode() != expected:
		raise ClientComponentError(f"Checksum mismatch for {path.name}: expected {integrity}")


def display_path(path):
	"""`path` relative to the current folder, or as it is when it's on another drive (Windows)."""

	try:
		return os.path.relpath(path)
	except ValueError:
		return path
