"""What the docs site holds, read once when the app starts: the guide, made from README.md's
sections (the single source of the reference documentation), the tutorial's steps, the
navigation and the search index."""

import importlib
import re
import sys
from collections import namedtuple
from pathlib import Path

import markup


DOCS = Path(__file__).resolve().parent
ROOT = DOCS.parent
README = ROOT / "README.md"
TUTORIAL = DOCS / "tutorial"

# A README section: "## Styles" or "### Server push", with its own text (not its subsections')
Section = namedtuple("Section", "title level slug text")

# A guide page: its README sections, in order, and a sentence that introduces them
Topic = namedtuple("Topic", "slug title group lead sections")

# A tutorial step, from tutorial/<slug>.md
Step = namedtuple("Step", "slug number title lead text")

# Something the search finds: a page, or a heading on one
Entry = namedtuple("Entry", "title url context")


GUIDE = [
	Topic("installation", "Installation", "Start", "Install Domino and run the examples.", ["Install", "Run an example"]),

	Topic("components", "Components", "Guide", "Classes that render HTML, keep state and handle events.", ["Components", "Attributes"]),
	Topic("state", "State", "Guide", "Values that re-render what shows them when they change.", ["State"]),
	Topic("events", "Events", "Guide", "Clicks, typing and submits, handled in Python on the server.", ["Events", "Loading and errors"]),
	Topic("devtools", "Developer tools", "Guide", "Error pages, the component inspector and the event log, while debugging.", ["Developer tools"]),
	Topic("styles", "Styles", "Guide", "CSS on the component class, scoped to it and written once per page.", ["Styles"]),
	Topic("tailwind", "Tailwind CSS", "Guide", "Tailwind classes anywhere, with nothing to install or build.", ["Tailwind CSS", "Your own theme", "Tailwind in production", "Caveats"]),
	Topic("templates", "Templates", "Guide", "Components written as HTML: template strings and Jinja.", ["Templates", "Template strings (Python 3.14)", "Jinja templates"]),
	Topic("forms", "Forms", "Guide", "Fields declared once, checked in the browser and on the server.", ["Forms"]),
	Topic("pages", "Pages & navigation", "Guide", "File-based routing, layouts, and page switches without reloading.", ["Pages", "Moving between pages"]),
	Topic("reactive-data", "Reactive data & MongoDB", "Guide", "Collections that re-render every open page when they change.", ["Reactive data", "MongoDB"]),
	Topic("server-push", "Server push", "Guide", "Update open pages from anywhere, without waiting for an event.", ["Server push"]),
	Topic("instant-ui", "Instant UI", "Guide", "Clicks that show at once, even on a slow connection.", ["Instant updates", "Simulating a slow connection"]),
	Topic("client-components", "Client components", "Guide", "Experimental: components that run in the browser, in Python.", ["Experimental: client components"]),
	Topic("accounts", "Accounts", "Guide", "Sign-up, login, password reset and email verification, with GitHub and Google.", ["Accounts", "Password reset, email verification and changing the password", "GitHub and Google"]),
	Topic("email", "Email", "Guide", "Sending email, printed while debugging and captured in tests.", ["Email"]),
	Topic("uploads", "File uploads", "Guide", "File inputs whose files arrive in your handler.", ["File uploads"]),

	Topic("settings", "Settings", "Reference", "settings.json, local overrides and environment variables.", ["Settings"]),
	Topic("testing", "Testing", "Reference", "Tests next to their page, in a simulated browser.", ["Testing your app", "MongoDB in tests"]),
	Topic("deployment", "Deployment", "Reference", "Deploy with one command, and serve on every CPU core.", ["Deploying", "Serving in production"]),
	Topic("cli", "Command line", "Reference", "domino create, run, serve, build and deploy.", ["Command line", "Hot reloading", "Development MongoDB"]),
	Topic("how-it-works", "How it works", "Reference", "One WebSocket per tab, and the HTTP fallback.", ["How the browser talks to the server"]),
	Topic("contributing", "Contributing", "Reference", "Run Domino's own tests, publish a release, and the license.", ["Tests", "Releasing", "License"]),
]


def read_sections(text):
	"""README.md's "##" and "###" sections, in order, each with its own text."""

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


SECTIONS = {section.title: section for section in read_sections(README.read_text(encoding="utf-8"))}
TOPICS = {topic.slug: topic for topic in GUIDE}

# Each README anchor's guide page, so README links (#testing-your-app) lead to it
ANCHORS = {SECTIONS[title].slug: topic.slug for topic in GUIDE for title in topic.sections}


def guide_link(href):
	"""A link in README.md, as it should be in the docs."""

	if href.startswith("#"):
		topic = ANCHORS.get(href[1:])
		return f"/guide/{topic}{href}" if topic else href

	# A file of the repository (examples/counter/...), shown on GitHub
	if not re.match(r"^[a-z]+:|^/", href):
		return markup.repository_link(href)

	return href


def topic_parts(topic):
	"""A guide page's content, its README sections rendered: ("html", Markup) and ("code",
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


def step_parts(step):
	"""A step's content: ("html", Markup), ("code", language, source), ("file", path) and
	("demo", folder) parts, in order."""

	parts = []
	pieces = DIRECTIVE.split(step.text)
	for index in range(0, len(pieces), 3):
		parts.extend(markup.render(pieces[index]))
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
	path = str(TUTORIAL / folder)
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
