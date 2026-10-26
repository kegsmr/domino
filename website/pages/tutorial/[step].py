import time

from flask import abort

import domino.tags as t

import content
import markup
from components.code import Code
from components.demo import Demo
from components.prose import blocks
from components.shell import Toc


LANGUAGES = {".py": "python", ".html": "html", ".json": "json", ".md": "markdown"}

# Shared by everyone reading the docs (an in-memory Collection), so kept short
DEMO_TASKS = 12


# /tutorial/<step>: a step of the tutorial, from tutorial/<step>.md. The code it shows is read
# from that step's app, in tutorial/<folder>/, and its demos are that app's own component
def page(step):

	step = content.STEP_SLUGS.get(step)
	if step is None:
		abort(404)

	def part(part):

		kind, path = part
		if kind == "file":
			_, _, name = path.partition("/")
			source = (content.STEP_APPS / path).read_text(encoding="utf-8").rstrip("\n")
			language = LANGUAGES.get((content.STEP_APPS / path).suffix, "")
			return Code(source, language, caption=name)

		component = content.step_component(path)
		tidy(component)
		return Demo(component(), note=f"{path}/components/tasks.py, running on this page")

	headings = [(heading, markup.slug(heading)) for heading in content.step_headings(step)]

	return t.div(class_="doc") [
		t.article()([
			t.p(class_="eyebrow") [
				f"Tutorial · step {step.number} of {len(content.STEPS)}"
			],
			t.h1() [
				step.title
			],
			t.p(class_="lead") [
				step.lead
			]
		] + blocks(content.step_parts(step), part)),
		Toc(headings)
	]


def tidy(component):
	"""Keep a shared demo's tasks few, and start it with some."""

	tasks = component.render.__globals__.get("tasks")
	if tasks is None or tasks.name is not None:
		return

	items = tasks.find(sort=[("created", -1)]).fetch()
	if not items:
		tasks.insert({"text": "Read the tutorial", "done": True, "created": time.time()})
		tasks.insert({"text": "Open this page in a second tab", "done": False, "created": time.time() + 0.001})
	elif len(items) > DEMO_TASKS:
		tasks.remove({"_id": {"$in": [item["_id"] for item in items[DEMO_TASKS:]]}})
