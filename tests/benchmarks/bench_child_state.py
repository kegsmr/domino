"""How long a parent with 1,000 child components takes to render again, now that each child is
matched to the one before it (and keeps its State).

	python tests/benchmarks/bench_child_state.py [--rows 1000] [--runs 30]

Prints the median and best time of a click that re-renders the list (keyed, and without keys),
measured through the test client (the handler, the render and the predictions). Not collected by
pytest.
"""

import argparse
import statistics
import time

import domino.tags as t
from domino import Domino, State
from domino.components import Document


class Row(t.li):

	name = ""
	clicks = State(0)


	def click(self):

		self.clicks += 1


	def render(self):

		return [t.button(on_click=self.click) [f"{self.name} {self.clicks}"]]


def make_app(rows, keyed):

	class List(t.div):

		other = State(0)


		def bump(self):

			self.other += 1


		def render(self):

			if keyed:
				items = [Row(key=index, name=f"row {index}") for index in range(rows)]
			else:
				items = [Row(name=f"row {index}") for index in range(rows)]
			return [t.button(class_="bump", on_click=self.bump) [f"bump {self.other}"], t.ul() (items)]


	app = Domino(__name__)

	@app.route("/")
	def index():

		return Document() [List()]

	return app


def main():

	parser = argparse.ArgumentParser()
	parser.add_argument("--rows", type=int, default=1000)
	parser.add_argument("--runs", type=int, default=30)
	options = parser.parse_args()

	for keyed in (True, False):
		page = make_app(options.rows, keyed).test_page("/")
		page.click(".bump")
		times = []
		for _ in range(options.runs):
			start = time.perf_counter()
			page.click(".bump")
			times.append(time.perf_counter() - start)
		name = "no keys"
		if keyed:
			name = "keyed"
		print(f"{options.rows} rows, {name}: median {statistics.median(times) * 1000:.1f} ms, best {min(times) * 1000:.1f} ms")


if __name__ == "__main__":
	main()
