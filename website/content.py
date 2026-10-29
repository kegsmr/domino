"""What the docs site holds, read once when the app starts: the guide, made from the Markdown
pages in guide/ (the reference documentation, readable on GitHub too), the tutorial's steps,
the navigation and the search index."""

import importlib
import re
import sys
from collections import namedtuple
from pathlib import Path

import markup


SITE = Path(__file__).resolve().parent
ROOT = SITE.parent
DOCS = ROOT / "docs"
GUIDE_FOLDER = DOCS / "guide"
# The tutorial's text (docs/tutorial/<n>-<name>.md), and each step's complete app (tutorial/<n>-<name>/)
TUTORIAL = DOCS / "tutorial"
STEP_APPS = SITE / "tutorial"

# A section of a guide page: "## Styles" or "### Server push", with its own text (not its subsections')
Section = namedtuple("Section", "title level slug text")

# A guide page, guide/<slug>.md: "# Title", a sentence that introduces it, then its sections
Topic = namedtuple("Topic", "slug title group lead sections")

# A tutorial step, from tutorial/<slug>.md
Step = namedtuple("Step", "slug number title lead text")

# Something the search finds: a page, or a heading on one
Entry = namedtuple("Entry", "title url context")


# The guide's pages, in the order of the navigation, and the group each is in
GUIDE_PAGES = [
	("installation", "Start"),

	("components", "Guide"),
	("state", "Guide"),
	("events", "Guide"),
	("devtools", "Guide"),
	("styles", "Guide"),
	("tailwind", "Guide"),
	("templates", "Guide"),
	("forms", "Guide"),
	("pages", "Guide"),
	("reactive-data", "Guide"),
	("server-push", "Guide"),
	("instant-ui", "Guide"),
	("client-components", "Guide"),
	("accounts", "Guide"),
	("email", "Guide"),
	("uploads", "Guide"),

	("settings", "Reference"),
	("testing", "Reference"),
	("deployment", "Reference"),
	("desktop", "Reference"),
	("cli", "Reference"),
	("how-it-works", "Reference"),
	("contributing", "Reference"),
]


def read_sections(text):
	"""A page's "##" and "###" sections, in order, each with its own text."""

	sections = []
	title = level = None
	lines = []
	fenced = False

	def finish():
		if title is not None:
			sections.append(Section(title, level, markup.slug(title), "\n".join(lines).strip()))

	for line in text.splitlines():
		if line.startswith("```"):
			fenced = not fenced
		match = None if fenced else re.match(r"^(#{2,3}) (.+?)\s*$", line)
		if match:
			finish()
			level, title, lines = len(match.group(1)), match.group(2), []
		elif title is not None:
			lines.append(line)

	finish()

	return sections


def read_topic(slug, group):
	"""guide/<slug>.md as a Topic, and its sections. The text before its first "##" is the
	section named like the page."""

	text = (GUIDE_FOLDER / f"{slug}.md").read_text(encoding="utf-8")
	match = re.match(r"# (.+)\n+(.+?)\n\n", text)
	if match is None:
		raise ValueError(f"guide/{slug}.md starts with \"# Title\", then a sentence that introduces the page")
	title, lead = match.group(1).strip(), match.group(2).strip()
	sections = read_sections(f"## {title}\n\n{text[match.end():]}")

	return Topic(slug, title, group, lead, [section.title for section in sections]), sections


GUIDE = []
SECTIONS = {}
for _slug, _group in GUIDE_PAGES:
	_topic, _sections = read_topic(_slug, _group)
	GUIDE.append(_topic)
	for _section in _sections:
		if _section.title in SECTIONS:
			raise ValueError(f"Two guide sections are called {_section.title!r}; their links would clash")
		SECTIONS[_section.title] = _section
TOPICS = {topic.slug: topic for topic in GUIDE}

# Each section's guide page, so links to a section (#testing-your-app) lead to it
ANCHORS = {SECTIONS[title].slug: topic.slug for topic in GUIDE for title in topic.sections}


def guide_link(href):
	"""A link in a guide page, as it should be on the site: another page's section
	(testing.md#mongodb-in-tests), a section (#testing-your-app), or a file of the repository
	(../../examples/counter/), shown on GitHub."""

	page = re.match(r"^([a-z0-9-]+)\.md(#.*)?$", href)
	if page and page.group(1) in TOPICS:
		return f"/guide/{page.group(1)}{page.group(2) or ''}"

	if href.startswith("#"):
		topic = ANCHORS.get(href[1:])
		return f"/guide/{topic}{href}" if topic else href

	if not re.match(r"^[a-z]+:|^/", href):
		path = href[len("../../"):] if href.startswith("../../") else f"docs/guide/{href}"
		return markup.repository_link(path)

	return href


def topic_parts(topic):
	"""A guide page's content, its sections rendered: ("html", Markup) and ("code",
	language, source) parts. Each section is headed by its title, but for the one named like
	the page, whose title is the page's."""

	text = []
	for title in topic.sections:
		if title != topic.title:
			text.append(f"## {title}")
		text.append(SECTIONS[title].text)

	return markup.render("\n\n".join(text), guide_link)


def topic_headings(topic):

	return [title for title in topic.sections if title != topic.title]


# The tutorial: tutorial/1-first-page.md, ... Each is Markdown, whose lines like
# {{ file: 1-first-page/components/tasks.py }} show that file and {{ demo: 1-first-page }}
# run that step's Tasks component on the page
DIRECTIVE = re.compile(r"^\{\{\s*(file|demo):\s*(\S+)\s*\}\}\s*$", re.M)


def read_step(path):

	text = path.read_text(encoding="utf-8")
	heading, _, text = text.partition("\n")
	lead, _, text = text.strip().partition("\n\n")

	return Step(path.stem, int(path.stem.split("-")[0]), heading.lstrip("# ").strip(), lead.strip(), text.strip())


STEPS = [read_step(path) for path in sorted(TUTORIAL.glob("*.md"), key=lambda path: int(path.stem.split("-")[0]))]
STEP_SLUGS = {step.slug: step for step in STEPS}


def step_link(href):
	"""A link in a tutorial step, as it should be on the site: a guide page
	(../guide/testing.md#mongodb-in-tests) or the guide's index (../README.md)."""

	if href == "../README.md":
		return "/guide"

	if href.startswith("../guide/"):
		return guide_link(href[len("../guide/"):])

	return href


def step_parts(step):
	"""A step's content: ("html", Markup), ("code", language, source), ("file", path) and
	("demo", folder) parts, in order."""

	parts = []
	pieces = DIRECTIVE.split(step.text)
	for index in range(0, len(pieces), 3):
		parts.extend(markup.render(pieces[index], step_link))
		if index + 2 < len(pieces):
			parts.append((pieces[index + 1], pieces[index + 2]))

	return parts


def step_headings(step):

	return re.findall(r"^## (.+?)\s*$", step.text, re.M)


# The modules each step's app imports by these names, which also exist in other steps and in
# the docs app itself (components/)
STEP_MODULES = ("components", "data")
_demos = {}


def step_component(folder, name="components.tasks", cls="Tasks"):
	"""A tutorial step's component class, imported from that step's own files (its data.py
	and components/), without mixing them up with another step's or the docs app's."""

	key = (folder, name, cls)
	if key in _demos:
		return _demos[key]

	def ours(module):
		return module.split(".")[0] in STEP_MODULES

	saved = {module: sys.modules.pop(module) for module in list(sys.modules) if ours(module)}
	path = str(STEP_APPS / folder)
	sys.path.insert(0, path)
	try:
		importlib.invalidate_caches()
		component = _demos[key] = getattr(importlib.import_module(name), cls)
	finally:
		sys.path.remove(path)
		for module in list(sys.modules):
			if ours(module):
				del sys.modules[module]
		sys.modules.update(saved)

	return component


# The sidebar: (group, [(label, url)])
NAV = [
	("Start", [("Overview", "/"), ("Installation", "/guide/installation")]),
	("Tutorial", [("Introduction", "/tutorial")] + [(f"{step.number}. {step.title}", f"/tutorial/{step.slug}") for step in STEPS]),
	("Guide", [(topic.title, f"/guide/{topic.slug}") for topic in GUIDE if topic.group == "Guide"]),
	("Reference", [(topic.title, f"/guide/{topic.slug}") for topic in GUIDE if topic.group == "Reference"]),
]

PAGES = [(label, url) for _, links in NAV for label, url in links]
TITLES = {url: label for label, url in PAGES}
TITLES.update({f"/tutorial/{step.slug}": step.title for step in STEPS})
TITLES.update({"/tutorial": "Tutorial", "/guide": "Guide", "/search": "Search"})


def neighbors(path):
	"""The pages before and after `path` in the sidebar's order, or None."""

	urls = [url for _, url in PAGES]
	if path not in urls:
		return None, None

	index = urls.index(path)
	before = PAGES[index - 1] if index > 0 else None
	after = PAGES[index + 1] if index + 1 < len(PAGES) else None

	return before, after


def build_index():

	entries = [Entry("Overview", "/", "Domino"), Entry("Tutorial", "/tutorial", "Tutorial")]

	for step in STEPS:
		url = f"/tutorial/{step.slug}"
		entries.append(Entry(step.title, url, f"Tutorial · step {step.number}"))
		entries.extend(Entry(heading, f"{url}#{markup.slug(heading)}", step.title) for heading in step_headings(step))

	for topic in GUIDE:
		url = f"/guide/{topic.slug}"
		entries.append(Entry(topic.title, url, topic.group))
		for title in topic.sections:
			# A page's first section usually repeats its title
			if title != topic.title:
				entries.append(Entry(title, f"{url}#{SECTIONS[title].slug}", topic.title))

	return entries


INDEX = build_index()


def search(query, limit=8):
	"""Entries whose title has every word of `query`: pages before headings, and among each,
	titles that start with it first, then those with a word that does, then the rest."""

	words = query.lower().split()
	if not words:
		return []

	found = []
	for position, entry in enumerate(INDEX):
		title = entry.title.lower()
		if not all(word in title for word in words):
			continue
		phrase = " ".join(words)
		if title.startswith(phrase):
			rank = 0
		elif re.search(r"\b" + re.escape(words[0]), title):
			rank = 1
		else:
			rank = 2
		heading = "#" in entry.url
		found.append((heading, rank, position, entry))

	found.sort(key=lambda item: item[:3])

	return [entry for *_, entry in found[:limit]]


def version():
	"""Domino's version, from setup.py."""

	match = re.search(r'version="([^"]+)"', (ROOT / "setup.py").read_text(encoding="utf-8"))

	return match.group(1) if match else ""
