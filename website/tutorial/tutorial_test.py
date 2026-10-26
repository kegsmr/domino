# The tutorial's code works: each step's folder is a complete app, run here as `domino run`
# would, and the code the tutorial shows is read from those very files, so the two can't drift

import re
import shlex
import time
from pathlib import Path

import pytest

from domino.cli import build_parser
from domino.pytest_plugin import load_app


# Each step's complete app is here; its text is docs/tutorial/<n>-<name>.md
TUTORIAL = Path(__file__).resolve().parent
STEPS = sorted((TUTORIAL.parents[1] / "docs" / "tutorial").glob("*.md"), key=lambda path: int(path.stem.split("-")[0]))
DIRECTIVE = re.compile(r"^\{\{\s*(file|demo):\s*(\S+)\s*\}\}\s*$", re.M)
FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.M | re.S)


def folders():
	"""The steps' app folders, in the order the tutorial first shows them."""

	order = []
	for step in STEPS:
		for _, path in DIRECTIVE.findall(step.read_text(encoding="utf-8")):
			folder = path.split("/")[0]
			if folder not in order:
				order.append(folder)

	return order + sorted(path.name for path in TUTORIAL.iterdir() if (path / "pages").is_dir() and path.name not in order)


FOLDERS = folders()
def directives(kind):

	return [(step, path) for step in STEPS for found, path in DIRECTIVE.findall(step.read_text(encoding="utf-8")) if found == kind]


def app_files(folder):

	return sorted(path.relative_to(TUTORIAL / folder).as_posix() for path in (TUTORIAL / folder).rglob("*.py") if "__pycache__" not in path.parts)


def open_step(folder, path="/", client=None):

	app = load_app(TUTORIAL / folder)

	return app.test_page(path, client)


def sign_up(page, name):

	page.load("/signup?next=/")
	page.fill("input[name=name]", name)
	page.fill("input[name=email]", f"{name.lower()}@example.com")
	page.fill("input[name=password]", "correct horse battery")
	page.click("button", text="Sign up")


def test_every_step_has_an_app_and_every_file_it_names_exists():

	assert [step.stem for step in STEPS] == ["1-first-page", "2-events-and-forms", "3-styles", "4-pages-and-layouts", "5-reactive-data", "6-accounts", "7-testing", "8-deploying"]

	for step, path in directives("file"):
		assert (TUTORIAL / path).is_file(), f"{step.name} shows {path}, which doesn't exist"
	for step, folder in directives("demo"):
		assert (TUTORIAL / folder / "components" / "tasks.py").is_file(), f"{step.name} runs {folder}"


def test_every_file_of_every_app_is_shown_or_unchanged_from_a_step_before():

	shown = {path for _, path in directives("file")}

	for index, folder in enumerate(FOLDERS):
		for name in app_files(folder):
			if f"{folder}/{name}" in shown:
				continue
			# Not shown in its step: then it's the file an earlier step showed (or kept), as is
			source = (TUTORIAL / folder / name).read_text(encoding="utf-8")
			earlier = [before for before in FOLDERS[:index] if (TUTORIAL / before / name).is_file()]
			assert earlier, f"{folder}/{name} isn't shown in the tutorial"
			assert (TUTORIAL / earlier[-1] / name).read_text(encoding="utf-8") == source, \
				f"{folder}/{name} changed since {earlier[-1]}, but the tutorial doesn't show it"


def test_commands_in_the_tutorial_are_real():

	parser = build_parser()
	commands = 0

	for step in STEPS:
		for language, block in FENCE.findall(step.read_text(encoding="utf-8")):
			assert language in ("bash", "python", "json"), f"{step.name}: a ``` block without a language"
			if language == "python":
				compile(block, step.name, "exec")
			for line in block.splitlines():
				if line.startswith("domino "):
					# Exits (SystemExit) on anything `domino` wouldn't accept
					parser.parse_args(shlex.split(line)[1:])
					commands += 1

	assert commands >= 5


def test_step_1_a_component_with_state():

	page = open_step("1-first-page")

	assert page.text("h1") == "Tasks"
	page.click("button", text="Add a task")

	assert [item.text for item in page.find_all("li")] == ["Read the tutorial", "Build something", "Task 3"]
	assert page.text("p") == "3 tasks"


@pytest.mark.parametrize("folder", ["2-events-and-forms", "3-styles", "4-pages-and-layouts"])
def test_steps_2_to_4_events_and_forms(folder):

	page = open_step(folder)

	page.fill("input[name=text]", "Buy milk")
	page.click("button", text="Add")

	assert [item.text for item in page.find_all("li")] == ["Read the tutorial", "Build something", "Buy milk"]
	assert page.value("input[name=text]") == ""

	# "Read the tutorial" starts done
	page.click("button", text="Clear done")
	page.check("li input[type=checkbox]")
	page.click("button", text="Clear done")

	assert [item.text for item in page.find_all("li")] == ["Buy milk"]


def test_step_3_styles_and_theme():

	page = open_step("3-styles")

	assert ".Tasks li.done {" in page.html
	assert "@media (prefers-color-scheme: dark)" in page.html


def test_step_4_pages_and_layouts():

	home = open_step("4-pages-and-layouts")
	about = open_step("4-pages-and-layouts", "/about")

	assert home.find("nav a[aria-current=page]").text == "Tasks"
	assert about.find("nav a[aria-current=page]").text == "About"
	assert about.text("h1") == "About"
	assert home.find_all(".Tasks") != []


def test_step_5_tasks_are_shared_live():

	first = open_step("5-reactive-data")
	second = open_step("5-reactive-data")

	# The in-memory collection lives as long as the app, so other tests may have added tasks
	text = f"Shared task {time.time()}"
	first.fill("input[name=text]", text)
	first.click("button", text="Add")
	second.sync()

	assert second.find_all("li")[-1].text == text


def test_step_5_in_mongodb(_domino_database):

	_domino_database.app = load_app(TUTORIAL / "5-mongodb")
	first = open_step("5-mongodb")
	second = open_step("5-mongodb")

	first.fill("input[name=text]", "Stored in MongoDB")
	first.click("button", text="Add")
	second.sync()

	assert [item.text for item in second.find_all("li")] == ["Stored in MongoDB"]

	second.check("li input[type=checkbox]")
	second.click("button", text="Clear done")
	first.sync()

	assert first.find_all("li") == []


def test_step_6_accounts(_domino_database):

	_domino_database.app = load_app(TUTORIAL / "6-accounts")
	page = open_step("6-accounts")
	visitor = open_step("6-accounts")

	assert page.text("main p") == "Log in to add tasks."

	sign_up(page, "Ada")

	assert page.path == "/"
	assert "Signed in as Ada" in page.text("nav")

	page.fill("input[name=text]", "Buy milk")
	page.click("button", text="Add")
	visitor.sync()

	assert visitor.text("main li") == "Buy milk Ada"
	assert visitor.find_all("main form") == []

	page.click("button", text="Log out")

	assert page.text("main p") == "Log in to add tasks."


def test_step_7_has_tests_next_to_its_page():

	# They run with the rest of the suite, as page tests (see the plugin, domino/pytest_plugin.py)
	assert (TUTORIAL / "7-testing" / "pages" / "index_test.py").is_file()
	assert "def test_" in (TUTORIAL / "7-testing" / "pages" / "index_test.py").read_text(encoding="utf-8")
