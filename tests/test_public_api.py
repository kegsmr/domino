"""The public surface: what `from domino import ...` and `import domino.` offer. New internals
must not leak back in; the old paths of modules made private keep working for a release."""

import importlib
import logging
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

import domino


PUBLIC = [
	"Domino",
	"Component", "Document", "State", "Collection", "Event",
	"redirect", "batch", "wait", "html", "template",
	"TemplateError",
	"t",
	"request", "session", "g", "abort", "url_for",
]

PUBLIC_MODULES = ["accounts", "bootstrap", "forms", "mail", "mongo", "tags", "testing"]

MOVED = [
	"core", "reactive", "templates", "dtemplates", "components", "util", "css", "optimistic", "patches",
	"hot", "workers", "devmongo", "devtools", "asgi", "pytest_plugin", "settings", "client", "uploads",
	"pages", "tailwind", "deploy", "cli",
]


def test_from_domino_import_offers_what_apps_use():

	assert domino.__all__ == PUBLIC
	assert dir(domino) == sorted(PUBLIC + PUBLIC_MODULES)

	namespace = {}
	exec("from domino import *", namespace)
	assert sorted(name for name in namespace if name != "__builtins__") == sorted(PUBLIC)


def test_the_public_modules_are_the_only_ones_without_an_underscore():

	folder = Path(domino.__file__).parent
	modules = sorted(path.stem for path in folder.glob("*.py") if not path.stem.startswith("_"))

	assert modules == PUBLIC_MODULES
	for name in PUBLIC_MODULES:
		importlib.import_module(f"domino.{name}")


def test_flask_and_helpers_dont_leak_in():

	# (Old module paths someone imported, like the pytest plugin of an older install, are set too)
	names = {name for name in vars(domino) if not name.startswith("_")} - set(MOVED)

	assert names - set(PUBLIC) - set(PUBLIC_MODULES) <= {"Core", "PublicSettings", "PageStore", "MemoryPageStore"}
	for leaked in ("Blueprint", "os", "json", "render_stack", "worker_prefix", "SESSION_HANDOFF_TTL"):
		assert leaked not in names


@pytest.mark.parametrize("name", MOVED)
def test_old_module_paths_still_work_with_a_deprecation_warning(name):

	sys.modules.pop(f"domino.{name}", None)
	with warnings.catch_warnings(record=True) as caught:
		warnings.simplefilter("always")
		module = importlib.import_module(f"domino.{name}")

	assert module is importlib.import_module(f"domino._{name}")
	assert module.__name__ == f"domino._{name}"
	assert any(issubclass(warning.category, DeprecationWarning) and f"domino.{name}" in str(warning.message) for warning in caught)


def test_old_imports_from_domino_still_work_with_a_deprecation_warning():

	with pytest.warns(DeprecationWarning, match="domino.Element"):
		from domino import Element  # noqa: F401
	sys.modules.pop("domino.components", None)
	with pytest.warns(DeprecationWarning, match="import Document from domino"):
		from domino.components import Document
	assert Document is domino.Document

	# Documented, so no warning
	with warnings.catch_warnings():
		warnings.simplefilter("error")
		from domino import Core, MemoryPageStore, PageStore, PublicSettings  # noqa: F401


def test_the_command_and_the_pytest_plugin_live_at_their_new_paths():

	setup = (Path(domino.__file__).parent.parent / "setup.py").read_text(encoding="utf-8")

	assert '"domino=domino._cli:main"' in setup
	assert '"domino=domino._pytest_plugin"' in setup
	result = subprocess.run([sys.executable, "-m", "domino", "--version"], capture_output=True, text=True, timeout=60,
		cwd=Path(domino.__file__).parent.parent)
	assert result.returncode == 0, result.stderr
	assert "DeprecationWarning" not in result.stderr


# Prop typos (#56)


def debug_app():

	app = domino.Domino(__name__)
	app.debug = True

	return app


def test_a_misspelled_prop_is_reported_with_a_suggestion(caplog):

	from domino import Component, State

	class TaskList(Component):

		tasks = []
		page = State(1)

	with debug_app().app_context(), caplog.at_level(logging.WARNING):
		TaskList(taks=["Buy milk"])
		TaskList(taks=["again"])  # once per class and name

	(message,) = [record.getMessage() for record in caplog.records]
	assert message == (
		"TaskList got taks=['Buy milk'], which isn't an attribute of TaskList, so it was written as an "
		"HTML attribute. Did you mean tasks?"
	)


def test_real_html_attributes_and_strings_are_not_reported(caplog):

	from domino import Component, t

	class Card(Component):

		title = ""

	with debug_app().app_context(), caplog.at_level(logging.WARNING):
		Card(title="x", class_=["a", "b"], style={"color": "red"}, id="c", data_count=3, aria_hidden=True,
			on_click=print, tilte="a string is fine")
		t.div(role="list", hidden=False, data_x=None)

	assert caplog.records == []


def test_no_report_outside_debug_mode(caplog):

	from domino import Component

	class Quiet(Component):

		items = []

	with domino.Domino(__name__).app_context(), caplog.at_level(logging.WARNING):
		Quiet(itmes=[1])
	Quiet(itmes=[2])  # no app at all

	assert caplog.records == []
