import importlib.util
import json
import os
import sys
import time
import uuid

import pytest

import domino.tags as t
from domino import Domino, State, TemplateError, html, template, wait
from domino.components import Document


# Template strings are Python 3.14 syntax, so their tests live in a module this one imports there
if sys.version_info >= (3, 14):
	pytest.register_assert_rewrite("_templates_314")
	from _templates_314 import *  # noqa: F401,F403
else:

	def test_html_explains_that_template_strings_need_python_314():

		with pytest.raises(RuntimeError, match="needs Python 3.14"):
			html("<p></p>")


def write(path, text):

	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(text, encoding="utf-8")

	return path


def import_file(path):

	name = f"domino_test_{uuid.uuid4().hex[:8]}"
	spec = importlib.util.spec_from_file_location(name, path)
	module = importlib.util.module_from_spec(spec)
	# Paired templates are found through the class's module
	sys.modules[name] = module
	spec.loader.exec_module(module)

	return module


def load(client):

	page = client.get("/").get_data(as_text=True)
	page_id = page.split('data-domino-page="')[1].split('"')[0]

	return page_id, page


def event_ids(page):

	ids = []
	for chunk in page.split('data-event-id="')[1:]:
		ids.extend(chunk.split('"')[0].split())

	return ids


def click(client, page_id, event_id):

	data = client.post("/_domino/events", json={"page_id": page_id, "event_id": event_id}).get_json()
	wait()

	return data


COUNTER = """
import domino.tags as t
from domino import State


class Counter(t.div):

	count = State(0)


	def increment(self):

		self.count += 1
"""

COUNTER_HTML = '<p>Count: {{ count }}</p><button {{ on(click=increment) }}>+</button>'


# Finding templates

def test_templates_are_found_by_name_anywhere_in_the_app(tmp_path):

	write(tmp_path / "templates" / "flask.html", "flask {{ name }}")
	write(tmp_path / "pages" / "deep" / "er" / "card.html", "card {{ name }}")
	app = Domino("app", root_path=str(tmp_path))

	with app.test_request_context():
		assert template("flask.html", name="a")._render() == "flask a"
		assert template("card.html", name="b")._render() == "card b"


def test_duplicate_names_fail_at_startup_listing_both(tmp_path):

	first = write(tmp_path / "a" / "card.html", "")
	second = write(tmp_path / "b" / "card.html", "")

	with pytest.raises(TemplateError) as error:
		Domino("app", root_path=str(tmp_path))

	assert str(first) in str(error.value) and str(second) in str(error.value)


def test_a_name_also_in_templates_folder_is_ambiguous(tmp_path):

	write(tmp_path / "templates" / "card.html", "")
	write(tmp_path / "parts" / "card.html", "")

	with pytest.raises(TemplateError, match="card.html"):
		Domino("app", root_path=str(tmp_path))


def test_hidden_and_tool_folders_are_skipped(tmp_path):

	write(tmp_path / "card.html", "mine")
	for folder in [".domino", ".git", "static", "node_modules", "__pycache__", "venv"]:
		write(tmp_path / folder / "card.html", "not mine")
	write(tmp_path / "venv" / "pyvenv.cfg", "")

	app = Domino("app", root_path=str(tmp_path))

	assert app.template_finder.index == {"card.html": str(tmp_path / "card.html")}


def test_edits_and_new_templates_are_picked_up_while_debugging(tmp_path):

	card = write(tmp_path / "parts" / "card.html", "old")
	app = Domino("app", root_path=str(tmp_path))
	app.debug = True

	with app.test_request_context():
		assert template("card.html")._render() == "old"
		card.write_text("new", encoding="utf-8")
		later = time.time() + 5
		os.utime(card, (later, later))
		assert template("card.html")._render() == "new"

		write(tmp_path / "parts" / "added.html", "added")
		assert template("added.html")._render() == "added"


# Jinja pages with components inside

def test_component_in_a_jinja_page_binds_and_re_renders(tmp_path):

	write(tmp_path / "page.html", "<html><head></head><body><h1>{{ title }}</h1>{{ component(Counter) }}{{ heading }}</body></html>")
	module = import_file(write(tmp_path / "widgets.py", COUNTER + "\n\n\tdef render(self):\n\n\t\treturn [t.p() [f'Count: {self.count}'], t.button(on_click=self.increment) ['+']]\n"))
	app = Domino("app", root_path=str(tmp_path))

	@app.route("/")
	def index():

		return template("page.html", title="<Hi>", Counter=module.Counter, heading=t.h2() ["Element"])

	client = app.test_client()
	page_id, page = load(client)

	assert "<h1>&lt;Hi&gt;</h1>" in page
	assert '<script class="Core" src="/_domino/core"' in page.split("</head>")[0]
	assert "<h2>" in page and "Element" in page
	assert "Count: 0" in page

	data = click(client, page_id, event_ids(page)[0])

	assert "Count: 1" in data["html"]


def test_template_as_a_child_of_a_document(tmp_path):

	write(tmp_path / "part.html", "<em>{{ word }}</em>")
	app = Domino("app", root_path=str(tmp_path))

	@app.route("/")
	def index():

		return Document() [template("part.html", word="hi")]

	assert "<em>hi</em>" in app.test_client().get("/").get_data(as_text=True)


# Components paired with a template

def serve(tmp_path, component):

	app = Domino("app", root_path=str(tmp_path))

	@app.route("/")
	def index():

		return Document() [component]

	client = app.test_client()
	page_id, page = load(client)

	return app, client, page_id, page


def test_paired_by_class_name(tmp_path):

	write(tmp_path / "components" / "todo_list.html", "<ul>{{ this.label }} {{ items|length }}</ul>")
	module = import_file(write(tmp_path / "components" / "lists.py", (
		"import domino.tags as t\nfrom domino import State\n\n\n"
		"class TodoList(t.div):\n\n\titems = State([1, 2])\n\tlabel = 'Todos'\n"
	)))

	_, _, _, page = serve(tmp_path, module.TodoList())

	assert "<ul>Todos 2</ul>" in page


def test_paired_by_module_name(tmp_path):

	write(tmp_path / "components" / "counter.html", COUNTER_HTML)
	module = import_file(write(tmp_path / "components" / "counter.py", COUNTER.replace("class Counter", "class Clicker")))

	_, _, _, page = serve(tmp_path, module.Clicker())

	assert "<p>Count: 0</p>" in page


def test_render_wins_over_a_paired_template(tmp_path):

	write(tmp_path / "counter.html", COUNTER_HTML)
	source = COUNTER + "\n\n\tdef render(self):\n\n\t\treturn [t.p() ['from render']]\n"
	module = import_file(write(tmp_path / "counter.py", source))

	_, _, _, page = serve(tmp_path, module.Counter())

	assert "from render" in page and "Count:" not in page


def test_events_from_a_paired_template_round_trip(tmp_path):

	write(tmp_path / "counter.html", COUNTER_HTML)
	module = import_file(write(tmp_path / "counter.py", COUNTER))

	app, client, page_id, page = serve(tmp_path, module.Counter())
	(event_id,) = event_ids(page.split("data-domino-predict")[0])

	data = click(client, page_id, event_id)
	assert "<p>Count: 1</p>" in data["html"]

	# Same id after the re-render, and the old registration was replaced, not added to
	assert event_ids(data["html"])[0] == event_id
	assert list(app.page_store.pages[page_id].events) == [event_id]
	assert "<p>Count: 2</p>" in click(client, page_id, event_id)["html"]


def test_state_read_in_a_paired_template_subscribes(tmp_path):

	write(tmp_path / "counter.html", COUNTER_HTML)
	module = import_file(write(tmp_path / "counter.py", COUNTER))
	counter = module.Counter()

	app, _, page_id, page = serve(tmp_path, counter)
	assert "data-live" in page

	counter.count = 7

	(update,) = app.page_store.pages[page_id].updates.values()
	assert "<p>Count: 7</p>" in update["html"]


def test_state_change_from_a_background_thread_renders_outside_a_request(tmp_path):

	write(tmp_path / "counter.html", COUNTER_HTML)
	module = import_file(write(tmp_path / "counter.py", COUNTER))
	counter = module.Counter()

	app, _, page_id, _ = serve(tmp_path, counter)

	import threading
	thread = threading.Thread(target=lambda: setattr(counter, "count", 3))
	thread.start()
	thread.join()

	(update,) = app.page_store.pages[page_id].updates.values()
	assert "<p>Count: 3</p>" in update["html"]


def test_predictions_for_a_paired_template_counter(tmp_path):

	write(tmp_path / "counter.html", COUNTER_HTML)
	module = import_file(write(tmp_path / "counter.py", COUNTER))

	_, _, _, page = serve(tmp_path, module.Counter())
	predictions = json.loads(page.split("data-domino-predict>")[1].split("</script>")[0])

	assert len(predictions) == 1
	assert "<p>Count: 1</p>" in next(iter(predictions.values()))


def test_on_with_several_events_and_debounce(tmp_path):

	write(tmp_path / "search.html", "<input {{ on(input=search, change=search, debounce=250) }}>")
	module = import_file(write(tmp_path / "search.py", (
		"import domino.tags as t\n\n\nclass Search(t.div):\n\n\tdef search(self):\n\n\t\tpass\n"
	)))

	_, _, _, page = serve(tmp_path, module.Search())
	ids = event_ids(page)

	assert [event_id.rsplit("-", 1)[1] for event_id in ids] == ["input", "change"]
	assert 'data-debounce-input="250" data-debounce-change="250"' in page


def test_re_rendering_drops_events_of_components_embedded_by_the_template(tmp_path):

	write(tmp_path / "panel.html", "{{ component(this.Counter) }}<button {{ on(click=refresh_me) }}>r</button>")
	source = COUNTER + "\n\n\tdef render(self):\n\n\t\treturn [t.button(on_click=self.increment) ['+']]\n"
	widgets = import_file(write(tmp_path / "widgets.py", source))
	module = import_file(write(tmp_path / "panel.py", (
		"import domino.tags as t\n\n\nclass Panel(t.div):\n\n\tdef refresh_me(self):\n\n\t\tpass\n"
	)))
	module.Panel.Counter = widgets.Counter

	app, client, page_id, page = serve(tmp_path, module.Panel())
	events = app.page_store.pages[page_id].events
	assert len(events) == 2

	(refresh,) = [event_id for event_id, (_, callback) in events.items() if callback.__name__ == "refresh_me"]
	click(client, page_id, refresh)

	# The new Counter's event replaced the old one's
	assert len(events) == 2


def test_component_css_in_a_jinja_page_goes_in_its_head(tmp_path):

	write(tmp_path / "page.html", "<!DOCTYPE html>\n<html><head><title>x</title><style>p { color: blue; }</style></head><body>{{ component(Badge) }}{{ component(Badge) }}</body></html>")

	class Badge(t.span):

		css = {"color": "red"}

		def render(self):
			return ["!"]

	app = Domino("app", root_path=str(tmp_path))

	@app.route("/")
	def index():
		return template("page.html", Badge=Badge)

	html = app.test_client().get("/").get_data(as_text=True)

	# Still a standards-mode document, with the CSS once, before the template's own styles
	assert html.startswith("<!DOCTYPE html>")
	assert html.count(".Badge {") == 1
	assert html.index("<head>") < html.index('data-domino-css="Badge"') < html.index("p { color: blue; }")
