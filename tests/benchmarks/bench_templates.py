"""Rendering a 100-row list three ways: tag classes, a Jinja template and a Domino template.

	python tests/benchmarks/bench_templates.py [rows] [repeats]

Each row has a value, a class from a helper and a button bound to a handler with the row's index.
The component is rendered whole (as for a page load or an event response), outside predictions.
"""

import importlib.util
import os
import sys
import tempfile
import timeit
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from domino import Domino  # noqa: E402


PYTHON = '''
import domino.tags as t
from domino import State


ROWS = [{"name": f"Row {i}", "done": i % 3 == 0} for i in range(int(__import__("os").environ["BENCH_ROWS"]))]


class Tags(t.div):

	items = State(ROWS)

	def render(self):
		return [
			t.h2() ["Items"],
			t.ul()(
				[
					t.li(class_="done" if item["done"] else "open") [
						t.span() [item["name"]],
						t.button(on_click=lambda event, index=index: self.remove(index)) ["x"],
					]
					for index, item in enumerate(self.items)
				]
			),
		]

	def remove(self, index):
		self.items = self.items[:index] + self.items[index + 1:]


class JinjaList(t.div):

	items = State(ROWS)

	def remove(self, index):
		self.items = self.items[:index] + self.items[index + 1:]


class DominoList(t.div):

	items = State(ROWS)

	def item_class(self, item):
		return "done" if item["done"] else "open"

	def remove(self, index):
		self.items = self.items[:index] + self.items[index + 1:]
'''

# Jinja has no per-item handler binding, so its button binds the method (on() can't take values)
JINJA = '''<h2>Items</h2>
<ul>
{% for item in items %}	<li class="{{ 'done' if item.done else 'open' }}"><span>{{ item.name }}</span><button {{ on(click=remove) }}>x</button></li>
{% endfor %}</ul>
'''

DOMINO = '''<DominoList>
	<h2>Items</h2>
	<ul>
		<li each="index, item in enumerate(items)" :class="item_class(item)"><span>{{ item.name }}</span><button on-click="remove(index)">x</button></li>
	</ul>
</DominoList>
'''


def main(rows=100, repeats=200):

	os.environ["BENCH_ROWS"] = str(rows)
	folder = Path(tempfile.mkdtemp(prefix="domino-bench-"))
	(folder / "lists.py").write_text(PYTHON)
	(folder / "jinja_list.html").write_text(JINJA)
	(folder / "domino_list.html").write_text(DOMINO)

	name = f"bench_{uuid.uuid4().hex[:6]}"
	spec = importlib.util.spec_from_file_location(name, folder / "lists.py")
	module = importlib.util.module_from_spec(spec)
	sys.modules[name] = module
	spec.loader.exec_module(module)

	app = Domino("bench", root_path=str(folder))

	results = {}
	with app.test_request_context():
		for label, cls in [("tag classes", module.Tags), ("Jinja template", module.JinjaList), ("Domino template", module.DominoList)]:
			component = cls()
			html = component._render()
			assert html.count("<li") == rows, (label, html[:500])
			seconds = min(timeit.repeat(component._render, number=repeats, repeat=5)) / repeats
			results[label] = seconds
			print(f"{label:16} {seconds * 1000:7.3f} ms per render  ({len(html):,} bytes)")

	base = results["Domino template"]
	for label, seconds in results.items():
		if label != "Domino template":
			print(f"Domino template is {seconds / base:.1f}x as fast as {label}")


if __name__ == "__main__":

	main(*(int(arg) for arg in sys.argv[1:]))
