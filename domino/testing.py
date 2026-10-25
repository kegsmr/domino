"""Test Domino apps without a browser: load a page, click, type and submit, and read the result.

	page = app.test_page("/")
	page.click("button", text="Increment")
	assert page.text("p") == "Current Count: 1"

Events go through the same endpoint the browser uses, so handlers, State, reactive data and
updates pushed from other pages all run for real; only the browser is simulated.
"""

import mimetypes
import os
import re
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path

from . import reactive


VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
FIELDS = {"input", "select", "textarea"}
TOGGLES = {"checkbox", "radio"}


class DominoTestError(AssertionError):
	"""Something the test asked for didn't work (no such element, a handler failed, ...)."""


class Node:
	"""An element of the page under test."""


	def __init__(self, tag, attrs, parent=None):

		self.tag = tag
		self.attrs = dict(attrs)
		self.children = []
		self.parent = parent
		self.value = None  # what the user typed or picked, when it differs from the HTML
		self.files = None  # a file input's picked files: [(filename, bytes, content_type)]


	def __repr__(self):

		attrs = "".join(f' {key}="{value}"' for key, value in self.attrs.items() if key in ("id", "class", "name", "type"))
		return f"<{self.tag}{attrs}>"


	@property
	def text(self):
		"""The element's text, with whitespace collapsed like a browser shows it."""

		parts = []
		stack = [self]
		while stack:
			node = stack.pop()
			if isinstance(node, str):
				parts.append(node)
			elif node.tag not in ("script", "style", "template"):
				stack.extend(reversed(node.children))

		return " ".join("".join(parts).split())


	def elements(self):
		"""Every element below this one, in document order."""

		for child in self.children:
			if isinstance(child, Node):
				yield child
				yield from child.elements()


	def closest(self, tag):

		node = self
		while node is not None and node.tag != tag:
			node = node.parent

		return node


	def field_value(self):
		"""The value a field has now: typed by the test, or else as rendered."""

		if self.value is not None:
			return self.value
		if self.tag == "textarea":
			return "".join(child for child in self.children if isinstance(child, str))
		if self.tag == "select":
			options = [option for option in self.elements() if option.tag == "option"]
			for option in options:
				if "selected" in option.attrs:
					return option.attrs.get("value", option.text)
			if options:
				return options[0].attrs.get("value", options[0].text)
			return ""
		if self.attrs.get("type") in TOGGLES:
			return "checked" in self.attrs

		return self.attrs.get("value", "")


class TreeBuilder(HTMLParser):


	def __init__(self):

		super().__init__(convert_charrefs=True)
		self.root = Node("#document", {})
		self.current = self.root


	def handle_starttag(self, tag, attrs):

		node = Node(tag, [(key, value or "") for key, value in attrs], self.current)
		self.current.children.append(node)
		if tag not in VOID_TAGS:
			self.current = node


	def handle_startendtag(self, tag, attrs):

		self.current.children.append(Node(tag, [(key, value or "") for key, value in attrs], self.current))


	def handle_endtag(self, tag):

		node = self.current
		while node is not None and node.tag != tag:
			node = node.parent
		if node is not None and node.parent is not None:
			self.current = node.parent


	def handle_data(self, data):

		self.current.children.append(data)


def parse(html):

	builder = TreeBuilder()
	builder.feed(html)
	builder.close()

	return builder.root


# One compound selector: tag, #id, .class and [attr] / [attr=value] parts
SELECTOR_PART = re.compile(r"""([a-zA-Z][\w-]*)|#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:=["']?([^"'\]]*)["']?)?\]""")


def matches_compound(node, compound):

	position = 0
	while position < len(compound):
		part = SELECTOR_PART.match(compound, position)
		if part is None:
			raise DominoTestError(f"Unsupported selector: {compound!r}")
		tag, id_, class_, attr, value = part.groups()
		if tag and node.tag != tag.lower():
			return False
		if id_ and node.attrs.get("id") != id_:
			return False
		if class_ and class_ not in node.attrs.get("class", "").split():
			return False
		if attr and attr not in node.attrs:
			return False
		if attr and value is not None and node.attrs.get(attr) != value:
			return False
		position = part.end()

	return True


def matches(node, selector):
	"""Whether `node` matches a selector of compound parts separated by spaces (descendants)."""

	compounds = selector.split()
	if not matches_compound(node, compounds[-1]):
		return False

	ancestor = node.parent
	for compound in reversed(compounds[:-1]):
		while ancestor is not None and not (ancestor.tag != "#document" and matches_compound(ancestor, compound)):
			ancestor = ancestor.parent
		if ancestor is None:
			return False
		ancestor = ancestor.parent

	return True


class TestPage:
	"""A page of a Domino app, driven like a user would in a browser."""


	__test__ = False  # not a pytest test class, despite the name


	def __init__(self, app, path="/", client=None):

		self.app = app
		self.client = client or app.test_client()
		self.load(path)


	def load(self, path):
		"""Navigate this tab to `path` (redirects are followed, cookies kept)."""

		response = self.client.get(path, follow_redirects=True)
		self.status = response.status_code
		self.path = response.request.path
		self.root = parse(response.get_data(as_text=True))

		root = next((node for node in self.root.elements() if "data-domino-page" in node.attrs), None)
		self.page_id = None
		if root is not None:
			self.page_id = root.attrs["data-domino-page"]

		return self


	@property
	def html(self):

		return render(self.root)


	def find_all(self, selector, text=None):

		found = [node for node in self.root.elements() if matches(node, selector)]
		if text is not None:
			found = [node for node in found if text in node.text]

		return found


	def find(self, selector, text=None):

		found = self.find_all(selector, text)
		if not found:
			described = selector
			if text is not None:
				described += f" with text {text!r}"
			raise DominoTestError(f"No element matches {described}. Page text: {self.root.text[:300]!r}")

		return found[0]


	def text(self, selector=None):

		if selector is None:
			return self.root.text

		return self.find(selector).text


	def value(self, selector):

		return self.find(selector).field_value()


	def fill(self, selector, value):
		"""Set a field's value, like typing into it, without firing events."""

		node = self.find(selector)
		if node.tag not in FIELDS:
			raise DominoTestError(f"{node!r} isn't a form field")
		node.value = value

		return self


	def type(self, selector, value):
		"""Type into a field: set its value and fire its input event."""

		self.fill(selector, value)
		self.dispatch(self.find(selector), "input")

		return self


	def select(self, selector, value):

		self.fill(selector, value)
		self.dispatch(self.find(selector), "change")

		return self


	def check(self, selector, checked=True):

		node = self.find(selector)
		node.value = bool(checked)
		self.dispatch(node, "change")

		return self


	def upload(self, selector, *files):
		"""Pick files in a file input and fire its change event, like a user choosing them.
		Each file is a path, or (filename, bytes) or (filename, bytes, content_type). They're
		uploaded with the input's change event and with its form's submit, like in a browser."""

		node = self.find(selector)
		if node.tag != "input" or node.attrs.get("type") != "file":
			raise DominoTestError(f"{node!r} isn't a file input")
		if len(files) > 1 and "multiple" not in node.attrs:
			raise DominoTestError(f"{node!r} takes one file (it has no multiple attribute)")
		node.files = [read_file(file) for file in files]
		self.dispatch(node, "change")

		return self


	def click(self, selector, text=None):
		"""Click an element; a submit button also submits its form, like in a browser."""

		node = self.find(selector, text)
		if node.tag == "input" and node.attrs.get("type") in TOGGLES:
			node.value = not node.field_value()
			self.dispatch(node, "click")
			self.dispatch(node, "change")
			return self

		self.dispatch(node, "click")

		form = node.closest("form")
		submits = node.tag == "button" and node.attrs.get("type", "submit") == "submit"
		submits = submits or (node.tag == "input" and node.attrs.get("type") == "submit")
		if form is not None and submits:
			self.dispatch(form, "submit")

		return self


	def submit(self, selector="form"):

		self.dispatch(self.find(selector), "submit")

		return self


	def dispatch(self, node, event_type):
		"""Fire `event_type` on `node` and every ancestor bound to it (events bubble)."""

		page_id = self.page_id
		element = node
		while element is not None and element.tag != "#document":
			for event_id in element.attrs.get("data-event-id", "").split():
				if event_id.rsplit("-", 1)[-1] == event_type and self.page_id == page_id:
					self.send(element, event_id)
			element = element.parent


	def send(self, element, event_id):

		data = {}
		if element.tag in FIELDS:
			data["value"] = element.field_value()
		form = element.closest("form")
		if form is not None:
			data["form"] = form_data(form)

		# Like the browser, files go up first, to get a token per file for the event
		files = selected_files(element)
		if files:
			data["files"] = self.upload_files(files)

		response = self.client.post("/_domino/events", json={"page_id": self.page_id, "event_id": event_id, "data": data})
		payload = response.get_json(silent=True) or {}
		if response.status_code == 404:
			raise DominoTestError("The page expired (or the event doesn't exist any more)")
		if response.status_code != 200:
			message = payload.get("traceback") or payload.get("error") or response.status_code
			raise DominoTestError(f"The event handler failed: {message}")

		# The handler called domino.redirect(): the browser goes there instead
		if payload.get("redirect"):
			self.load(payload["redirect"])
			return

		# Like the browser, the fields of the element that fired take the server's state
		for node in [element, *element.elements()]:
			node.files = None
		self.apply(payload, element)
		self.sync()


	def upload_files(self, files):

		body = {}
		for name, (filename, content, content_type) in files:
			body.setdefault(name, []).append((BytesIO(content), filename, content_type))

		response = self.client.post("/_domino/upload", data=body, headers={"X-Domino-Page": self.page_id or ""})
		payload = response.get_json(silent=True) or {}
		if response.status_code != 200:
			raise DominoTestError(f"The upload failed: {payload.get('error') or response.status_code}")

		return payload["files"]


	def run_timers(self):
		"""Fire every pending `after` timer now, instead of waiting for it."""

		for node in [node for node in self.root.elements() if "data-after-id" in node.attrs]:
			self.send(node, node.attrs["data-after-id"])

		return self


	def sync(self):
		"""Apply updates the server pushed to this page (e.g. changes made by other pages)."""

		reactive.wait()
		page = self.app.page_store.load(self.page_id) if self.page_id else None
		if page is None:
			return self

		with page.updates_ready:
			updates = list(page.updates.values())
			page.updates.clear()
		for update in sorted(updates, key=lambda update: update.get("version", 0)):
			self.apply(update, None)

		return self


	def apply(self, payload, reset):

		if not payload.get("id") or not payload.get("html"):
			return

		target = next((node for node in self.root.elements() if node.attrs.get("id") == payload["id"]), None)
		if target is None:
			return
		replacement = next(parse(payload["html"]).elements(), None)
		if replacement is None:
			return

		# Like the browser, keep what the user typed unless the server changed the field,
		# or the field is inside the element that fired the event
		typed = {}
		for node in [target, *target.elements()]:
			if node.tag in FIELDS and node.value is not None and node.attrs.get("name"):
				submitted = reset is not None and (node is reset or is_inside(node, reset))
				if not submitted:
					typed[node.attrs["name"]] = (node.value, node.attrs.get("value"))
		for node in [replacement, *replacement.elements()]:
			name = node.attrs.get("name")
			if node.tag in FIELDS and name in typed and typed[name][1] == node.attrs.get("value"):
				node.value = typed[name][0]

		parent = target.parent
		replacement.parent = parent
		parent.children[parent.children.index(target)] = replacement


def is_inside(node, ancestor):

	while node is not None:
		if node is ancestor:
			return True
		node = node.parent

	return False


def form_data(form):
	"""A form's fields as the browser sends them (unchecked boxes left out, repeats as lists)."""

	data = {}
	for node in form.elements():
		name = node.attrs.get("name")
		if node.tag not in FIELDS or not name or "disabled" in node.attrs:
			continue
		# Files go up on their own (see selected_files)
		if node.attrs.get("type") == "file":
			continue
		if node.attrs.get("type") in TOGGLES:
			if not node.field_value():
				continue
			value = node.attrs.get("value", "on")
		else:
			value = node.field_value()
		if name in data:
			if not isinstance(data[name], list):
				data[name] = [data[name]]
			data[name].append(value)
		else:
			data[name] = value

	return data


def selected_files(element):
	"""[(name, file)] an event on `element` uploads, as the browser does: a file input's own
	files, or those of every file input in a submitted form."""

	if element.tag == "input" and element.attrs.get("type") == "file":
		inputs = [element]
	elif element.tag == "form":
		inputs = [node for node in element.elements() if node.tag == "input" and node.attrs.get("type") == "file"]
	else:
		return []

	files = []
	for node in inputs:
		name = node.attrs.get("name") or ("file" if node is element else None)
		if name and node.files and "disabled" not in node.attrs:
			files.extend((name, file) for file in node.files)

	return files


def read_file(file):
	"""(filename, bytes, content_type) for a path or a (filename, bytes[, content_type]) tuple."""

	if isinstance(file, (str, os.PathLike)):
		path = Path(file)
		file = (path.name, path.read_bytes())
	if isinstance(file, tuple) and len(file) == 2:
		file = (*file, mimetypes.guess_type(file[0])[0] or "application/octet-stream")
	filename, content, content_type = file
	if isinstance(content, str):
		content = content.encode()

	return filename, content, content_type


def render(node):

	if isinstance(node, str):
		return node

	inner = "".join(render(child) for child in node.children)
	if node.tag == "#document":
		return inner

	attrs = "".join(f' {key}="{value}"' for key, value in node.attrs.items())
	if node.tag in VOID_TAGS:
		return f"<{node.tag}{attrs}>"

	return f"<{node.tag}{attrs}>{inner}</{node.tag}>"
