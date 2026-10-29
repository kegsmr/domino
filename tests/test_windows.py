"""Windows (domino.windows): <window name="Settings"> definitions, opened by open-window= or
open_window(), served at /_domino/window/<Name>, and closed by close_window()."""

import json
import textwrap

import pytest

from domino import Domino, TemplateError, Window, close_window, open_window, windows
from domino.dtemplates import parse_file


@pytest.fixture(autouse=True)
def forget_app(tmp_path, forget_modules):

	yield

	forget_modules(tmp_path)


def write(path, text):

	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")

	return path


def make_app(tmp_path):

	app = Domino("app", root_path=str(tmp_path))
	app.testing = True

	return app


SETTINGS = '''
<window name="Settings" title="Preferences" width="420" height="300" min-width="320" resizable="false" class="settings">
	<p>{{ tab }}</p>
	<button on-click="close">Done</button>
</window>
'''


def settings_app(tmp_path, page='<page><button open-window="Settings">Settings</button></page>'):

	write(tmp_path / "windows" / "settings.html", SETTINGS)
	write(tmp_path / "windows" / "settings.py", """
		from domino import Window


		class Settings(Window):

			tab = "general"
	""")
	write(tmp_path / "pages" / "index.html", page)

	return make_app(tmp_path)


# Definitions


def test_a_window_keeps_its_options_apart_from_its_attributes(tmp_path):

	compiled = parse_file(str(write(tmp_path / "settings.html", SETTINGS)))
	definition = compiled.definitions["Settings"]

	assert definition.kind == "window"
	assert definition.window == {"title": "Preferences", "width": 420, "height": 300, "min-width": 320, "resizable": False}
	assert definition.root[0] == [("class", "settings")]


def test_a_windows_title_defaults_to_its_name(tmp_path):

	compiled = parse_file(str(write(tmp_path / "help.html", '<window name="Help"><p>?</p></window>')))

	assert compiled.definitions["Help"].window == {"title": "Help"}


@pytest.mark.parametrize("markup, message", [
	('<window name="W" width="wide"><p></p></window>', "a size in pixels"),
	('<window name="W" resizable="maybe"><p></p></window>', "true or false"),
	('<window name="W" title="{{ name }}"><p></p></window>', "a value, not"),
	('<window main width="400"><p>hello</p></window>', "leave it empty"),
	('<window main name="Main"></window>', "needs no name"),
])
def test_window_mistakes_say_what_to_write(tmp_path, markup, message):

	with pytest.raises(TemplateError, match=message):
		parse_file(str(write(tmp_path / "w.html", markup)))


def test_open_window_names_a_window(tmp_path):

	write(tmp_path / "pages" / "index.html", '<page><button open-window="settings">x</button></page>')

	with pytest.raises(TemplateError, match="open-window= names a window"):
		make_app(tmp_path).test_page("/")


# Opening and closing


def test_open_window_opens_it_with_its_options(tmp_path):

	page = settings_app(tmp_path).test_page("/")
	page.click("button")

	assert page.windows == [{
		"name": "Settings", "url": "/_domino/window/Settings",
		"title": "Preferences", "width": 420, "height": 300, "min-width": 320, "resizable": False,
	}]

	window = page.window("Settings")
	assert window.status == 200
	assert window.text("title") == "Preferences"
	assert window.text("p") == "general"
	assert window.find(".settings") is not None


def test_a_window_opened_from_python_gets_values(tmp_path):

	write(tmp_path / "components" / "menu.py", """
		import domino.tags as t
		from domino import open_window


		class Menu(t.div):

			def audio(self):
				open_window("Settings", tab="audio")
	""")
	write(tmp_path / "components" / "menu.html", '<component name="Menu"><button on-click="audio">Audio</button></component>')
	page = settings_app(tmp_path, "<page><Menu /></page>").test_page("/")
	page.click("button")

	assert page.windows[0]["url"] == "/_domino/window/Settings?values=" + "%7B%22tab%22%3A+%22audio%22%7D"
	assert page.window("Settings").text("p") == "audio"


def test_a_window_closes_itself(tmp_path):

	page = settings_app(tmp_path).test_page("/")
	page.click("button")
	window = page.window("Settings")

	assert not window.closed
	window.click("button", text="Done")
	assert window.closed


def test_a_window_without_a_class_can_close_itself(tmp_path):

	write(tmp_path / "windows" / "about.html", '<window name="About" width="300" height="200"><button on-click="close">OK</button></window>')
	write(tmp_path / "pages" / "index.html", '<page><button open-window="About">About</button></page>')
	page = make_app(tmp_path).test_page("/")
	page.click("button")
	window = page.window("About")

	window.click("button", text="OK")
	assert window.closed


def test_windows_update_each_other_like_tabs(tmp_path):

	write(tmp_path / "data.py", """
		from domino import State

		theme = State("light")
	""")
	write(tmp_path / "windows" / "settings.html", '<window name="Settings"><button on-click="dark">Dark</button></window>')
	write(tmp_path / "windows" / "settings.py", """
		from domino import Window

		from data import theme


		class Settings(Window):

			def dark(self):
				theme.value = "dark"
	""")
	write(tmp_path / "components" / "shown.py", """
		import domino.tags as t

		from data import theme


		class Shown(t.div):

			def current(self):
				return theme.value
	""")
	write(tmp_path / "components" / "shown.html", '<component name="Shown"><p>{{ current }}</p></component>')
	write(tmp_path / "pages" / "index.html", '<page><Shown /><button open-window="Settings">Settings</button></page>')
	page = make_app(tmp_path).test_page("/")

	page.click("button", text="Settings")
	page.window("Settings").click("button", text="Dark")
	page.sync()

	assert page.text("p") == "dark"


def test_a_window_can_be_in_a_layout(tmp_path):

	write(tmp_path / "layouts" / "main.html", """
		<layout name="Main">
			<html>
				<head><title>{{ title }} · App</title></head>
				<body><nav>nav</nav><slot /></body>
			</html>
		</layout>
	""")
	write(tmp_path / "windows" / "help.html", '<window name="Help" layout="Main"><p>Help!</p></window>')
	write(tmp_path / "pages" / "index.html", '<page><button open-window="Help">?</button></page>')
	page = make_app(tmp_path).test_page("/")
	page.click("button")
	window = page.window("Help")

	assert window.text("title") == "Help · App"
	assert window.text("nav") == "nav"
	assert window.text("p") == "Help!"


def test_open_and_close_only_in_a_handler(tmp_path):

	settings_app(tmp_path)

	with pytest.raises(windows.WindowError, match="from an event handler"):
		open_window("Settings")
	with pytest.raises(windows.WindowError, match="from an event handler"):
		close_window()


def test_a_window_that_doesnt_exist_or_values_that_arent_json(tmp_path):

	write(tmp_path / "components" / "menu.py", """
		import domino.tags as t
		from domino import open_window


		class Menu(t.div):

			def missing(self):
				open_window("Nope")

			def odd(self):
				open_window("Settings", when=object())
	""")
	write(tmp_path / "components" / "menu.html", '<component name="Menu"><button on-click="missing">a</button><button on-click="odd">b</button></component>')
	page = settings_app(tmp_path, "<page><Menu /></page>").test_page("/")

	from domino.testing import DominoTestError

	with pytest.raises(DominoTestError, match="No window called Nope"):
		page.click("button", text="a")
	with pytest.raises(DominoTestError, match="must be JSON"):
		page.click("button", text="b")


def test_the_window_route_answers_only_for_windows(tmp_path):

	client = settings_app(tmp_path).test_client()

	assert client.get("/_domino/window/Nope").status_code == 404
	assert client.get("/_domino/window/Settings?values=not-json").status_code == 400
	assert client.get("/_domino/window/Settings?values=" + json.dumps([1])).status_code == 400
	assert client.get("/_domino/window/Settings").status_code == 200


def test_window_class_opens_itself(tmp_path):

	write(tmp_path / "components" / "menu.py", """
		import domino.tags as t
		from domino import Window


		class Help(Window):
			pass


		class Menu(t.div):

			def show(self):
				Help.open(topic="keys")
	""")
	write(tmp_path / "components" / "menu.html", """
		<component name="Menu"><button on-click="show">?</button></component>
		<window name="Help" width="300" height="200"><p>{{ topic }}</p></window>
	""")
	write(tmp_path / "pages" / "index.html", "<page><Menu /></page>")
	page = make_app(tmp_path).test_page("/")
	page.click("button")

	# A value it doesn't declare is still a value, not an attribute of its element
	assert page.window("Help").text("p") == "keys"
