"""App settings: settings.json < settings.local.json < DOMINO_* environment variables."""

import json
import os
from pathlib import Path


ENV_PREFIX = "DOMINO_"

# Points at a different settings.json, like `meteor --settings`
ENV_PATH = "DOMINO_SETTINGS"


class SettingsError(ValueError):
	"""A settings file that can't be read as a JSON object."""


class Settings(dict):
	"""A dict whose keys can also be read as attributes (settings.mongo.url)."""


	def __init__(self, *args, **kwargs):

		super().__init__(*args, **kwargs)

		for key in list(self):
			self[key] = wrap(self[key])


	def __getattr__(self, name):

		try:
			return self[name]
		except KeyError:
			available = ", ".join(sorted(self)) or "none"
			raise AttributeError(f"No setting {name!r} (available: {available})") from None


def wrap(value):

	# Nested objects get attribute access too, including ones inside lists
	if isinstance(value, dict) and not isinstance(value, Settings):
		return Settings(value)

	if isinstance(value, list):
		return [wrap(item) for item in value]

	return value


def load_settings(root_path, path=None, environ=None):
	"""Read the app's settings. `path` is relative to `root_path` (default settings.json);
	the DOMINO_SETTINGS environment variable replaces it."""

	if environ is None:
		environ = os.environ

	if environ.get(ENV_PATH):
		path = Path(environ[ENV_PATH])
	else:
		path = Path(root_path) / (path or "settings.json")

	# settings.json -> settings.local.json
	local_path = path.with_suffix(".local" + path.suffix)

	settings = read_file(path)
	merge(settings, read_file(local_path))
	merge(settings, read_environ(environ))

	return Settings(settings)


def read_file(path):

	# Every file is optional, so a missing or blank one counts as empty
	try:
		text = Path(path).read_text(encoding="utf-8")
	except FileNotFoundError:
		return {}

	if not text.strip():
		return {}

	try:
		data = json.loads(text)
	except json.JSONDecodeError as error:
		raise SettingsError(f"Invalid JSON in {path} at line {error.lineno}, column {error.colno}: {error.msg}") from None

	if not isinstance(data, dict):
		raise SettingsError(f"{path} must contain a JSON object, not {type(data).__name__}")

	return data


def read_environ(environ):
	"""DOMINO_MONGO__URL=... -> {"mongo": {"url": ...}}. Values are parsed as JSON when they
	parse and kept as strings otherwise."""

	settings = {}

	# Sorted so DOMINO_MONGO comes before DOMINO_MONGO__URL, which then merges into it
	for name, raw in sorted(environ.items()):

		if not name.startswith(ENV_PREFIX) or name == ENV_PATH:
			continue

		keys = name[len(ENV_PREFIX):].lower().split("__")
		if not all(keys):
			continue

		try:
			value = json.loads(raw)
		except ValueError:
			value = raw

		target = settings
		for key in keys[:-1]:
			if not isinstance(target.get(key), dict):
				target[key] = {}
			target = target[key]
		target[keys[-1]] = value

	return settings


def merge(base, override):
	"""Deep-merge `override` into `base`: nested objects merge, lists and scalars replace."""

	for key, value in override.items():
		if isinstance(value, dict) and isinstance(base.get(key), dict):
			merge(base[key], value)
		else:
			base[key] = value

	return base


def script_json(value):
	"""JSON safe to put inside a <script> element: <, > and & can't close it or open a comment."""

	return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
