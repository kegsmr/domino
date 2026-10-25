import importlib.util
from pathlib import Path

import pytest

from domino.bootstrap import BootstrapCSS


EXAMPLES = sorted((Path(__file__).parent.parent / "examples").glob("*.py"))


@pytest.mark.parametrize("path", EXAMPLES, ids=[path.stem for path in EXAMPLES])
def test_example_home_page_renders(path):

	spec = importlib.util.spec_from_file_location(f"example_{path.stem}", path)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)

	response = module.app.test_client().get("/")

	assert response.status_code == 200


def test_bootstrap_components_construct():

	assert "bootstrap.min.css" in BootstrapCSS()._render()
