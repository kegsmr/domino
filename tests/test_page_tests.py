import subprocess
import sys
import textwrap

from domino import Domino


def write(folder, files):

	for name, content in files.items():
		path = folder / name
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(textwrap.dedent(content), encoding="utf-8")


def run_pytest(folder, *args):

	result = subprocess.run(
		[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args, str(folder)],
		capture_output=True, text=True, cwd=folder,
	)

	return result.returncode, result.stdout + result.stderr


COUNTER = """
	import domino.tags as t
	from domino import State


	class Counter(t.div):

		count = State(0)

		def render(self):
			return [t.p() [f"Count: {self.count}"], t.button(on_click=self.increment) ["+"]]

		def increment(self):
			self.count += 1
"""


def make_app(folder):

	write(folder, {
		"components/counter.py": COUNTER,
		"pages/index.py": """
			from components.counter import Counter

			def page():
				return Counter()
		""",
		"pages/blog/index.py": """
			import domino.tags as t

			def page():
				return t.h1() ["Blog"]
		""",
		"pages/blog/[slug].py": """
			import domino.tags as t

			def page(slug):
				return t.h1() [slug.replace("-", " ").title()]
		""",
		# Same file name as pages/index_test.py: they mustn't clash
		"pages/index_test.py": """
			def test_click(page):
				page.click("button")
				assert page.text("p") == "Count: 1"
		""",
		"pages/blog/index_test.py": """
			def test_title(page):
				assert page.text("h1") == "Blog"

			def test_other_paths(open_page):
				assert open_page("/").text("p") == "Count: 0"
		""",
		"pages/blog/[slug]_test.py": """
			def test_slug(open_page):
				assert open_page(slug="hello-world").text("h1") == "Hello World"
		""",
	})


def test_tests_next_to_pages_get_their_page(tmp_path):

	make_app(tmp_path)

	code, output = run_pytest(tmp_path)

	assert code == 0, output
	assert "4 passed" in output


def test_failures_show_pytest_assertion_details(tmp_path):

	make_app(tmp_path)
	write(tmp_path, {"pages/index_test.py": """
		def test_click(page):
			page.click("button")
			assert page.text("p") == "Count: 2"
	"""})

	code, output = run_pytest(tmp_path, "pages/index_test.py")

	assert code == 1
	# Rewritten assert: both sides shown
	assert "'Count: 1' == 'Count: 2'" in output


def test_a_parameter_page_needs_its_parameters(tmp_path):

	make_app(tmp_path)
	write(tmp_path, {"pages/blog/[slug]_test.py": """
		def test_slug(page):
			pass
	"""})

	code, output = run_pytest(tmp_path, "-k", "test_slug")

	assert code != 0
	assert "use open_page(slug=...)" in output


def test_handler_errors_come_with_their_traceback(tmp_path):

	make_app(tmp_path)
	write(tmp_path, {
		"pages/broken.py": """
			import domino.tags as t

			class Broken(t.div):
				def render(self):
					return [t.button(on_click=self.explode) ["Boom"]]

				def explode(self):
					raise ValueError("kaboom")

			def page():
				return Broken()
		""",
		"pages/broken_test.py": """
			def test_boom(page):
				page.click("button")
		""",
	})

	code, output = run_pytest(tmp_path, "pages/broken_test.py")

	assert code == 1
	assert "ValueError: kaboom" in output
	assert 'raise ValueError("kaboom")' in output


def test_test_files_are_not_pages(tmp_path):

	make_app(tmp_path)

	app = Domino("page_tests_app", root_path=str(tmp_path))
	rules = {rule.rule for rule in app.url_map.iter_rules()}

	assert {"/", "/blog", "/blog/<slug>"} <= rules
	assert not any("test" in rule for rule in rules)
