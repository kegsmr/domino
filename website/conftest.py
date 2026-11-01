import os
import sys

import pytest


# The docs site needs Markdown and Pygments (website/requirements.txt), which Domino itself doesn't;
# without them its tests are left out rather than failing
try:
	import markdown  # noqa: F401
	import pygments  # noqa: F401
except ImportError:
	collect_ignore_glob = ["*"]


SITE = os.path.dirname(os.path.abspath(__file__))


@pytest.fixture(autouse=True, scope="session")
def site_components():
	"""Tests that ran before these (Domino's own) may have left other apps' components/
	imported, or their folders on the import path; the site's pages need its own."""

	for name, module in list(sys.modules.items()):
		if name.split(".")[0] != "components":
			continue
		paths = [getattr(module, "__file__", None) or ""] + list(getattr(module, "__path__", None) or [])
		if not all(os.path.abspath(path).startswith(SITE + os.sep) for path in paths if path):
			del sys.modules[name]
