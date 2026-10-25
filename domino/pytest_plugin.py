"""Tests that live next to their page: pages/about_test.py tests pages/about.py.

	# pages/index_test.py
	def test_increment(page):
		page.click("button", text="Increment")
		assert page.text("p") == "Current Count: 1"

`page` is the page this file tests, already open in a simulated browser (domino.testing),
and `open_page(**params)` opens it with URL parameters (pages/users/[id]_test.py) or opens
any path of the app. Installed with Domino, so plain `pytest` finds these files.
"""

import importlib.util
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

import pytest


TEST_SUFFIX = "_test.py"

_apps = {}  # app folder -> its Domino app, loaded once per test session
_active = [None]  # the app folder whose modules (components, data, ...) are importable now


def page_test_target(path):
	"""(app folder, pages folder, page file) for a test file in a pages/ folder, else None."""

	path = Path(path)
	if not path.name.endswith(TEST_SUFFIX):
		return None

	for parent in path.parents:
		if parent.name == "pages":
			page = path.with_name(path.name[:-len(TEST_SUFFIX)] + ".py")
			return parent.parent, parent, page

	return None


def activate(folder):
	"""Make `folder`'s own modules importable, forgetting another app's same-named ones
	(two apps can both have components/ and data.py)."""

	folder = str(folder)
	previous = _active[0]
	if previous == folder:
		return

	if previous is not None:
		for name, module in list(sys.modules.items()):
			file = getattr(module, "__file__", None) or ""
			if file.startswith(previous + os.sep) and not name.startswith(("domino_page_tests.", "domino_app_", "domino_pages.")):
				del sys.modules[name]

	if folder in sys.path:
		sys.path.remove(folder)
	sys.path.insert(0, folder)
	_active[0] = folder


def load_app(folder):

	folder = Path(folder).resolve()
	activate(folder)

	app = _apps.get(folder)
	if app is None:
		from .cli import load_app as load

		app = _apps[folder] = load(folder)
		# Handler errors come back to the test with their traceback
		app.testing = True

	return app


def import_test_file(path, name):

	# Through sys.meta_path, so pytest's assertion rewriting still applies
	for finder in sys.meta_path:
		find_spec = getattr(finder, "find_spec", None)
		spec = find_spec and find_spec(name, [str(path.parent)])
		if spec is not None:
			break
	else:
		raise ImportError(f"Can't import {path}")

	module = importlib.util.module_from_spec(spec)
	sys.modules[name] = module
	spec.loader.exec_module(module)

	return module


class PageTestModule(pytest.Module):
	"""A test file in pages/, imported under a name of its own: pages/index_test.py and
	pages/blog/index_test.py would otherwise clash, both being "index_test"."""


	def _getobj(self):

		folder, _, _ = page_test_target(self.path)
		activate(folder.resolve())

		unique = re.sub(r"\W", "_", str(self.path.parent.resolve()))
		return import_test_file(self.path, f"domino_page_tests.{unique}.{self.path.stem}")


def pytest_pycollect_makemodule(module_path, parent):

	if page_test_target(module_path) is not None:
		return PageTestModule.from_parent(parent, path=Path(module_path))

	return None


@pytest.fixture
def open_page(request):
	"""Open the page this test file is next to (`open_page(id=3)` fills in [id]), or any
	path of its app (`open_page("/about")`). Each call is a new browser tab."""

	target = page_test_target(request.path)
	if target is None:
		raise pytest.UsageError(f"open_page and page only work in tests next to a page: pages/<page>{TEST_SUFFIX}")

	folder, pages, page_file = target
	app = load_app(folder)

	def open_(path=None, **params):

		if path is None:
			if not page_file.is_file():
				raise pytest.UsageError(f"{request.path.name} tests {page_file.name}, which doesn't exist; pass a path to open_page()")
			path = page_url(pages, page_file, params)

		return app.test_page(path)

	return open_


@pytest.fixture
def page(open_page):
	"""The page this test file is next to, open in a simulated browser."""

	return open_page()


def page_url(pages, page_file, params):

	from .pages import url_rule

	rule = url_rule(page_file.relative_to(pages))
	names = re.findall(r"<(?:\w+:)?(\w+)>", rule)
	missing = [name for name in names if name not in params]
	if missing:
		raise pytest.UsageError(f"{page_file.name} has URL parameters; use open_page({', '.join(f'{name}=...' for name in missing)})")

	def fill(match):
		converter, name = match.groups()
		# A [...rest] parameter is a path, so its slashes stay
		return quote(str(params[name]), safe="/" if converter == "path" else "")

	return re.sub(r"<(?:(\w+):)?(\w+)>", fill, rule)
