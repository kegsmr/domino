from pathlib import Path

import pytest

from domino.bootstrap import BootstrapCSS


EXAMPLES_DIR = Path(__file__).parent.parent / "examples"

# Every example is a folder with an app.py and its pages/
EXAMPLES = sorted(path.parent.name for path in EXAMPLES_DIR.glob("*/app.py"))


def example_param(name):

	# Examples with named Collections store them in MongoDB
	marks = []
	sources = [path.read_text(encoding="utf-8") for path in (EXAMPLES_DIR / name).rglob("*.py")]
	if any('Collection("' in source for source in sources):
		marks.append(pytest.mark.mongo)

	return pytest.param(name, id=name, marks=marks)


def test_every_example_is_a_folder():

	assert list(EXAMPLES_DIR.glob("*.py")) == []
	assert len(EXAMPLES) >= 14


@pytest.mark.parametrize("name", [example_param(name) for name in EXAMPLES])
def test_example_pages_render(name, load_example):

	app = load_example(name).app
	# Examples with accounts sign their session cookie with it
	app.secret_key = "test"
	client = app.test_client()

	# Every page without URL parameters, which includes the home page
	rules = [rule.rule for rule in app.url_map.iter_rules() if rule.endpoint.startswith("pages/") and not rule.arguments]
	assert "/" in rules

	for rule in rules:
		response = client.get(rule)
		# Pages that need a login send visitors to it
		if response.status_code == 302:
			assert response.location.startswith("/login?next="), rule
			continue
		assert response.status_code == 200, rule


def test_functional_example_has_a_layout_a_dynamic_page_and_a_404_page(load_example):

	client = load_example("functional").app.test_client()

	about = client.get("/about").get_data(as_text=True)
	hello = client.get("/hello/Ada").get_data(as_text=True)
	missing = client.get("/nowhere")

	assert 'href="/contact"' in about and "This site was built" in about
	assert "Hello, Ada!" in hello and 'href="/about"' in hello
	assert missing.status_code == 404
	assert "Page not found" in missing.get_data(as_text=True)
	assert 'href="/about"' in missing.get_data(as_text=True)


def test_bootstrap_components_construct():

	assert "bootstrap.min.css" in BootstrapCSS()._render()
