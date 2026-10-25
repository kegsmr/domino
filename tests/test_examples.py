import importlib.util
import sys
from pathlib import Path

import pytest

from domino.bootstrap import BootstrapCSS


EXAMPLES_DIR = Path(__file__).parent.parent / "examples"

# Single-file examples, and examples with their own folder (e.g. for settings.json)
EXAMPLES = sorted(EXAMPLES_DIR.glob("*.py")) + sorted(EXAMPLES_DIR.glob("*/app.py"))


def example_name(path):

	if path.name == "app.py":
		return path.parent.name

	return path.stem


@pytest.mark.parametrize("path", EXAMPLES, ids=[example_name(path) for path in EXAMPLES])
def test_example_home_page_renders(path):

	spec = importlib.util.spec_from_file_location(f"example_{example_name(path)}", path)
	module = importlib.util.module_from_spec(spec)
	# Flask finds the app's folder (for settings.json) through sys.modules
	sys.modules[spec.name] = module
	spec.loader.exec_module(module)

	response = module.app.test_client().get("/")

	assert response.status_code == 200


def test_bootstrap_components_construct():

	assert "bootstrap.min.css" in BootstrapCSS()._render()
