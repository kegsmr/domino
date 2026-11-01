"""Markdown and code highlighting for the docs: Markdown (the guide's sections, the tutorial's
prose) becomes HTML, with its code blocks split out so pages show them as Code components."""

import functools
import html
import re

import markdown
from markdown.extensions.toc import TocExtension
from markupsafe import Markup
from pygments import highlight as pygments_highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.util import ClassNotFound


# The code blocks Markdown makes: <pre><code class="language-python">...</code></pre>
CODE_BLOCK = re.compile(r'<pre><code(?: class="language-([\w+-]+)")?>(.*?)</code></pre>', re.S)

# Links to sections (#testing-your-app) and to files of the repository (examples/...)
HREF = re.compile(r'href="([^"]*)"')

REPOSITORY = "https://github.com/kegsmr/domino"


def slug(title):
	"""A heading's anchor, the way GitHub makes them: "Template strings (Python 3.14)" ->
	"template-strings-python-314", so links to sections (#testing-your-app) keep working."""

	text = re.sub(r"[^\w\- ]", "", title.strip().lower())

	return text.replace(" ", "-")


@functools.lru_cache(maxsize=None)
def highlight(source, language=""):
	"""Source code as HTML spans with Pygments' short class names (.k, .s, .c, ...), which
	the Code component colors."""

	try:
		lexer = get_lexer_by_name(language) if language else TextLexer()
	except ClassNotFound:
		lexer = TextLexer()

	return Markup(pygments_highlight(source, lexer, HtmlFormatter(nowrap=True)).rstrip("\n"))


def render(text, link=None):
	"""Markdown as a list of parts: ("html", Markup) and ("code", language, source). `link(href)`
	may rewrite each link's address."""

	# Headings get ids made like GitHub's, and a link to themselves
	toc = TocExtension(slugify=lambda title, separator: slug(title), permalink="#", permalink_class="anchor", permalink_title="")
	rendered = markdown.markdown(text, extensions=["fenced_code", "tables", toc])

	if link is not None:
		rendered = HREF.sub(lambda match: f'href="{html.escape(link(html.unescape(match.group(1))))}"', rendered)

	parts = []
	position = 0
	for match in CODE_BLOCK.finditer(rendered):
		before = rendered[position:match.start()].strip()
		if before:
			parts.append(("html", Markup(before)))
		parts.append(("code", match.group(1) or "", html.unescape(match.group(2)).rstrip("\n")))
		position = match.end()

	rest = rendered[position:].strip()
	if rest:
		parts.append(("html", Markup(rest)))

	return parts


def repository_link(path):
	"""A file or folder of the repository on GitHub."""

	path = path.lstrip("./")
	kind = "tree" if path.endswith("/") or "." not in path.rsplit("/", 1)[-1] else "blob"

	return f"{REPOSITORY}/{kind}/main/{path}"
