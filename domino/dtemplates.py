"""Domino templates: HTML for markup, Python for logic.

A component's markup lives in an .html file, inside a tag named after its class:

	<!-- components/todo_list.html -->
	<TodoList class="todos">
		<ul>
			<li each="item in items" :class="item_class(item)">
				{{ item.text }} <button on-click="remove(item)">×</button>
			</li>
			<li else>Nothing to do!</li>
		</ul>
		<Footer :count="remaining" />
	</TodoList>

- A capitalized tag at the top level of a file defines that component; anywhere else it uses one.
- each=, if=, elif= and else are attributes; there are no blocks.
- {{ name }}, :attr="name", if="name" and each="x in name" read values from Python: the
  component's State, properties, attributes and helper methods (called without arguments), and
  loop variables, with .attribute and ["key"] access. helper(x, "y") calls a method with values;
  `not x` negates. Nothing else: no operators, comparisons or filters.
- on-click="handler" binds an event to a method; on-click="remove(item)" binds it with values,
  each item its own.

Each file is parsed once (again when it changes, while debugging) into ops: static HTML merged
into strings, and the few dynamic parts. Rendering walks them, writing strings straight out;
only components are Domino elements. See README.md, "Templates".
"""

import ast
import difflib
import functools
import importlib
import importlib.util
import os
import re
import sys
import types
import uuid
from bisect import bisect_right
from html import unescape

from markupsafe import Markup, escape

from .core import Element, Page, VOID_TAGS, collect_styles, current_styles, note_render_error, render_stack
from .settings import script_json
from .templates import TemplateError


# Counts parses, for tests that check each file is parsed once
stats = {"parses": 0}

# path -> (modification time, Compiled)
_compiled = {}

# path -> (modification time, "domino" or "jinja")
_formats = {}

# Content is text up to the closing tag: raw for script and style, escaped values for these
RAW_TEXT = ("script", "style")
ESCAPABLE_RAW_TEXT = ("textarea", "title")

DIRECTIVES = ("each", "if", "elif", "else")

TAG_START = re.compile(r"<([A-Za-z][A-Za-z0-9:_.-]*)")
CLOSE_TAG = re.compile(r"</\s*([A-Za-z][A-Za-z0-9:_.-]*)\s*>")
ATTRIBUTE = re.compile(r"""([^\s"'<>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?""")
SPACE = re.compile(r"\s*")
VALUE_TAG = re.compile(r"\{\{(.*?)\}\}", re.S)

# Blocks, in Python's words, closed like HTML: {{ if x }}, {{ elif x }}, {{ else }}, {{ /if }},
# {{ for item in items }}, {{ /for }}
BLOCK = re.compile(r"\s*(if|elif|else|for|/\s*if|/\s*for)\b(.*)", re.S)

# Just "{{ x }}": the attribute's value is x itself
SINGLE_VALUE = re.compile(r"\s*\{\{(.*?)\}\}\s*", re.S)

OLD_BINDING = '":{name}" isn\'t Domino\'s syntax: write {name}="{{{{ {value} }}}}"'

DIRECTIVE_ATTRIBUTE = (
	"{name}= isn't how Domino templates show or repeat elements: wrap them in "
	"{{{{ if x }}}}...{{{{ else }}}}...{{{{ /if }}}} or {{{{ for item in items }}}}...{{{{ /for }}}}"
)
LEAD = re.compile(r"\n[ \t]*$")
MARKER = re.compile(r"\A\s*\{#\s*(domino|jinja)\s*#\}[ \t]*\n?")

# Jinja's own globals, and names only Jinja templates use: a {{ }} with one is Jinja
JINJA_NAMES = {
	"this", "self", "loop", "super", "caller", "varargs", "kwargs", "url_for", "component", "on",
	"request", "session", "g", "config", "get_flashed_messages", "range", "dict", "lipsum",
	"cycler", "joiner", "namespace",
}

# Functions and methods read as values are called without arguments, like helpers
CALLED = (types.MethodType, types.FunctionType, types.BuiltinMethodType, types.BuiltinFunctionType, functools.partial)

# Names every template can use, after its own
BUILTINS = {"enumerate": enumerate, "len": len}

# Names of Element itself (configure, render, tag, ...), never a component's values
ELEMENT_NAMES = set(dir(Element)) | {"content_root", "render", "init"}


# Format ------------------------------------------------------------------------------------

def source_format(path, source, setting=None):
	""""domino" or "jinja": {# jinja #} or {# domino #} at the top, a .jinja file, the setting
	{"templates": "jinja"}, or else whether the file uses anything only Jinja has ({% %}, {# #},
	filters, operators, Jinja's globals, {{ }} inside an attribute's value)."""

	marker = MARKER.match(source)
	if marker:
		return marker.group(1)
	if path.endswith(".jinja") or setting == "jinja":
		return "jinja"
	if "{%" in source or "{#" in source:
		return "jinja"

	for match in VALUE_TAG.finditer(source):
		if BLOCK.match(match.group(1)):
			continue
		try:
			expression = parse_expression(match.group(1))
		except TemplateError:
			return "jinja"
		if root_name(expression) in JINJA_NAMES:
			return "jinja"

	return "domino"


def file_format(path, setting=None):
	""""components" for a file of component definitions (its top level is <TodoList>...</TodoList>),
	else "domino" or "jinja" (see source_format)."""

	mtime = os.path.getmtime(path)
	cached = _formats.get(path)
	if cached is not None and cached[0] == mtime:
		return cached[1]

	from .templates import DEFINITION_START

	with open(path, encoding="utf-8") as file:
		source = file.read()
	kind = source_format(path, source, setting)
	if kind == "domino" and DEFINITION_START.match(source) and not is_page_path(path):
		kind = "components"
	_formats[path] = (mtime, kind)

	return kind


# The apps' pages folders (see TemplateFinder), so a page is known as one with or without an app
pages_folders = set()


def is_page_path(path):
	"""Whether `path` is a page template (see TemplateFinder.is_page)."""

	from .templates import is_page_template

	return any(is_page_template(path, folder) for folder in pages_folders)


def root_name(expression):

	while expression[0] in ("attr", "item", "not", "call"):
		expression = expression[1]

	return expression[1] if expression[0] == "name" else None


# Expressions -------------------------------------------------------------------------------

TOKEN = re.compile(r"""\s*(?:(?P<string>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(?P<number>-?\d+(?:\.\d+)?)|(?P<name>[A-Za-z_]\w*)|(?P<op>[.,()\[\]]))""")

LITERALS = {"True": True, "False": False, "None": None}


def tokenize(text):

	tokens = []
	pos = 0
	text = text.rstrip()
	while pos < len(text):
		match = TOKEN.match(text, pos)
		if not match or match.end() == pos:
			raise TemplateError(f"{text.strip()!r}: unexpected {text[SPACE.match(text, pos).end()]!r}")
		kind = match.lastgroup
		value = match.group(kind)
		if kind == "string":
			value = ast.literal_eval(value)
		elif kind == "number":
			value = ast.literal_eval(value)
		tokens.append((kind, value))
		pos = match.end()

	return tokens


class ExpressionParser:


	def __init__(self, text):

		self.text = text.strip()
		self.tokens = tokenize(text)
		self.pos = 0


	def error(self, message):

		return TemplateError(f"{self.text!r}: {message}. Templates only read values: name, name.attribute, name[\"key\"], helper(x, \"text\"), not name")


	def peek(self, value=None):

		if self.pos >= len(self.tokens):
			return None
		token = self.tokens[self.pos]
		if value is not None and token[1] != value:
			return None

		return token


	def take(self, value=None):

		token = self.peek(value)
		if token is None:
			raise self.error(f"expected {value!r}" if value else "it ends too soon")
		self.pos += 1

		return token


	def end(self):

		if self.peek() is not None:
			raise self.error(f"unexpected {self.peek()[1]!r}")


	def expression(self, calls=True):

		if self.peek("not") and self.tokens[self.pos][0] == "name":
			self.pos += 1
			return ("not", self.expression(calls))

		kind, value = self.take()
		if kind in ("string", "number"):
			return ("literal", value)
		if kind != "name":
			raise self.error(f"unexpected {value!r}")
		if value in LITERALS:
			return ("literal", LITERALS[value])

		node = ("name", value)
		while True:
			if self.peek(".") and self.peek()[0] == "op":
				self.pos += 1
				kind, attribute = self.take()
				if kind != "name":
					raise self.error(f"expected a name after '.', not {attribute!r}")
				node = ("attr", node, attribute)
			elif self.peek("[") and self.peek()[0] == "op":
				self.pos += 1
				kind, key = self.take()
				if kind not in ("string", "number"):
					raise self.error("[...] takes a string or a number, like item[\"text\"] or row[0]")
				self.take("]")
				node = ("item", node, key)
			elif self.peek("(") and self.peek()[0] == "op":
				if not calls:
					raise self.error("arguments can't call anything themselves")
				self.pos += 1
				args = []
				if not self.peek(")"):
					while True:
						args.append(self.expression(calls=False))
						if self.peek(")"):
							break
						self.take(",")
				self.take(")")
				return ("call", node, args)
			else:
				return node


def parse_expression(text, calls=True):

	parser = ExpressionParser(text)
	if not parser.tokens:
		raise TemplateError("an empty {{ }} or attribute value; it needs a name")
	expression = parser.expression(calls)
	parser.end()

	return expression


def parse_each(text):
	"""each="item in items" or each="key, value in pairs" -> ([names], expression)."""

	match = re.match(r"\s*([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s+in\s+(.+)$", text, re.S)
	if not match:
		raise TemplateError(f"each={text!r} needs the form each=\"item in items\" (or \"key, value in pairs\")")

	names = [name.strip() for name in match.group(1).split(",")]

	return names, parse_expression(match.group(2))


EVENT = object()  # in a handler's arguments, `event`: the Event, when the handler runs


class BoundCall:
	"""on-click="remove(item)": the handler with the values of this render (each loop item its
	own). Predicted like the component's own methods (see optimistic.predictable_callback)."""

	__slots__ = ("function", "args", "events", "__self__", "__name__", "__domino_call__")


	def __init__(self, function, args):

		self.function = function
		self.args = tuple(args)
		self.events = [index for index, value in enumerate(self.args) if value is EVENT]
		self.__self__ = getattr(function, "__self__", None)
		self.__name__ = getattr(function, "__name__", type(function).__name__)
		self.__domino_call__ = None
		if not self.events and isinstance(function, types.MethodType):
			self.__domino_call__ = (function, self.args)


	def __call__(self, event=None):

		args = self.args
		if self.events:
			args = list(args)
			for index in self.events:
				args[index] = event

		return self.function(*args)


	def __repr__(self):

		return f"<{self.__name__}{self.args!r}>"


def compile_expression(expression, where, mode="value"):
	"""A function of the render context returning the expression's value. mode "value" calls
	helpers read as values, "handler" makes an event handler, "argument" is an argument's value."""

	kind = expression[0]

	if kind == "literal":
		value = expression[1]
		return lambda context: value

	if kind == "not":
		inner = compile_expression(expression[1], where, mode)
		return lambda context: not inner(context)

	if kind == "call":
		function = compile_expression(expression[1], where, "callee")
		args = [compile_expression(argument, where, "argument") for argument in expression[2]]
		if mode == "handler":
			return lambda context: _bound_call(function(context), [arg(context) for arg in args], where)
		return lambda context: _call(function(context), [arg(context) for arg in args], where)

	# Only an event handler, or a helper about to be called with arguments, is left uncalled
	called = mode in ("value", "argument")

	if kind == "name":
		name = expression[1]
		if mode == "argument" and name == "event":
			return lambda context: EVENT

		def read(context):
			local = context.local
			if name in local:
				value = local[name]
			else:
				value = context.lookup(name, where)
			if called and isinstance(value, CALLED):
				value = value()
			return value

		return read

	base = compile_expression(expression[1], where, "value")
	key = expression[2]

	if kind == "attr":

		def read(context):
			value = _attribute(base(context), key, where)
			if called and isinstance(value, CALLED):
				value = value()
			return value

		return read

	def read(context):
		value = _item(base(context), key)
		if called and isinstance(value, CALLED):
			value = value()
		return value

	return read


def _attribute(value, name, where):

	if value is None:
		return None

	if isinstance(value, dict):
		if name in value:
			return value[name]
		found = getattr(value, name, None)
		return found if callable(found) else None

	try:
		return getattr(value, name)
	except AttributeError:
		pass

	try:
		return value[name]
	except (TypeError, KeyError, IndexError, AttributeError):
		pass

	names = [attribute for attribute in dir(value) if not attribute.startswith("_")]
	raise where.error(f"{type(value).__name__} has no attribute {name!r}", name, names)


def _item(value, key):

	if value is None:
		return None

	try:
		return value[key]
	except (KeyError, IndexError):
		return None
	except TypeError:
		return getattr(value, str(key), None)


def _call(function, args, where):

	if not callable(function):
		raise where.error(f"{function!r} isn't a helper that can be called")

	return function(*args)


def _bound_call(function, args, where):

	if not callable(function):
		raise where.error(f"the handler {function!r} can't be called")

	return BoundCall(function, args)


class Where:
	"""A place in a template, for errors: file:line:col and what's written there."""

	__slots__ = ("path", "line", "col", "text")


	def __init__(self, path, line, col, text):

		self.path = path
		self.line = line
		self.col = col
		self.text = text


	def __str__(self):

		return f"{shown_path(self.path)}:{self.line}:{self.col}"


	def error(self, message, name=None, names=()):

		message = f"{self}: {message}"
		if self.text:
			message += f", in {self.text}"
		if name is not None:
			close = difflib.get_close_matches(name, list(names), n=1)
			if close:
				message += f". Did you mean {close[0]!r}?"
			available = sorted(names)
			if available:
				shown = ", ".join(available[:30]) + (", ..." if len(available) > 30 else "")
				message += f" Available: {shown}"

		return TemplateError(message)


def shown_path(path):

	if not path:
		return "<template>"

	try:
		relative = os.path.relpath(path)
	except ValueError:
		return path

	return path if relative.startswith("..") else relative


# Parsing -----------------------------------------------------------------------------------

class Text:
	"""Template text: static HTML (str) and Where with an expression."""

	__slots__ = ("parts", "start")


	def __init__(self, parts, start):

		self.parts = parts
		self.start = start


	def blank(self):

		return all(isinstance(part, str) and not part.strip() for part in self.parts)


class Raw:
	"""Markup kept as it is: <!DOCTYPE html>."""

	__slots__ = ("text",)


	def __init__(self, text):

		self.text = text


class Tag:

	__slots__ = ("name", "attributes", "children", "where", "self_closing", "component", "end", "block", "opener")


	def __init__(self, name, where):

		self.name = name
		self.attributes = []  # (name, value or None, source text, Where)
		self.children = []
		self.where = where
		self.self_closing = False
		self.component = is_component_name(name)
		self.end = None
		# A block ({{ if x }}...{{ else }}...{{ /if }}) is a <template> with a directive: its
		# kind ("if", "elif", "else", "each") and the statement that opened it ("if" or "for")
		self.block = None
		self.opener = None


	def attribute(self, name):

		for attribute in self.attributes:
			if attribute[0] == name:
				return attribute

		return None


	def directive(self):

		if self.block is None:
			return None
		for name in DIRECTIVES:
			if self.attribute(name) is not None:
				return name

		return None


def is_component_name(name):

	# <DIV> is a div in old-style HTML; <TodoList> and <Card> are components
	from .tags import TAGS

	return name[:1].isupper() and not (name.isupper() and name.lower() in TAGS)


class Parser:


	def __init__(self, source, path):

		self.source = source
		self.path = path
		self.lines = [0] + [match.end() for match in re.finditer("\n", source)]
		self.pos = 0
		self.root = Tag("", None)
		self.stack = [self.root]


	def where(self, pos, text=""):

		line = bisect_right(self.lines, pos)

		return Where(self.path, line, pos - self.lines[line - 1] + 1, text)


	def error(self, pos, message):

		return TemplateError(f"{self.where(pos)}: {message}")


	def parse(self):

		source = self.source
		while self.pos < len(source):
			start = source.find("<", self.pos)
			if start == -1:
				self.text(self.pos, len(source))
				break
			self.text(self.pos, start)
			self.pos = start

			if source.startswith("<!--", start):
				end = source.find("-->", start + 4)
				if end == -1:
					raise self.error(start, "this comment is never closed with -->")
				self.pos = end + 3
			elif source.startswith("</", start):
				self.close_tag()
			elif source.startswith(("<!", "<?"), start):
				end = source.find(">", start)
				if end == -1:
					raise self.error(start, "<! is never closed with >")
				self.stack[-1].children.append(Raw(source[start:end + 1]))
				self.pos = end + 1
			elif TAG_START.match(source, start):
				self.open_tag()
			else:
				# A "<" that doesn't start a tag, as in "a < b"
				self.text(start, start + 1)
				self.pos = start + 1

		if len(self.stack) > 1:
			tag = self.stack[-1]
			if tag.block is not None:
				raise TemplateError(f"{tag.where}: {{{{ {tag.opener} }}}} is never closed; add {{{{ /{tag.opener} }}}}")
			raise TemplateError(f"{tag.where}: <{tag.name}> is never closed; add </{tag.name}>")

		return self.root.children


	def text(self, start, end, raw=None):
		"""Add source[start:end] to the open element, with its {{ }} values."""

		if start >= end:
			return

		text = self.source[start:end]
		parts = []
		pos = 0
		while True:
			open_ = text.find("{{", pos)
			if open_ == -1:
				break
			close = text.find("}}", open_ + 2)
			if close == -1:
				raise self.error(start + open_, "{{ is never closed with }}")
			code = text[open_ + 2:close]
			where = self.where(start + open_, f"{{{{{code}}}}}")
			if raw is None and BLOCK.match(code):
				before, after = text[pos:open_], close + 2
				# A block tag alone on its line takes the line with it, so it leaves no blank line
				line_start = before.rfind("\n")
				line_end = text.find("\n", after)
				rest = text[after:line_end if line_end != -1 else len(text)]
				at_line_start = line_start != -1 or start + pos == 0 or self.source[start + pos - 1] == "\n"
				if at_line_start and not before[line_start + 1:].strip() and not rest.strip():
					before = before[:line_start + 1]
					after = line_end + 1 if line_end != -1 else len(text)
				if before:
					parts.append(before)
				self.add_text(parts, start + pos)
				parts = []
				self.block(code, where)
				pos = after
				continue
			if open_ > pos:
				parts.append(text[pos:open_])
			try:
				expression = parse_expression(code)
			except TemplateError as error:
				raise TemplateError(f"{where}: {error}") from None
			parts.append((where, expression))
			pos = close + 2
		if pos < len(text):
			parts.append(text[pos:])

		self.add_text(parts, start, raw)


	def add_text(self, parts, start, raw=None):

		if not parts:
			return
		parent = self.stack[-1]

		# Text next to text (a "<" that wasn't a tag) joins it
		if parent.children and isinstance(parent.children[-1], Text) and raw is None:
			parent.children[-1].parts.extend(parts)
		else:
			parent.children.append(Text(parts, start))


	def block(self, code, where):
		"""{{ if x }}, {{ elif x }}, {{ else }}, {{ /if }}; {{ for item in items }}, {{ else }}
		(shown when the list is empty), {{ /for }}."""

		match = BLOCK.match(code)
		keyword, value = match.group(1).replace(" ", ""), match.group(2).strip()
		top = self.stack[-1]
		opened = next((tag for tag in reversed(self.stack) if tag.block is not None), None)

		if keyword in ("if", "for"):
			if not value:
				raise where.error("{{ for item in items }} needs the item and the list" if keyword == "for" else "{{ if }} needs a condition: {{ if done }}")
			tag = Tag("template", where)
			tag.opener = keyword
			if keyword == "for":
				if not re.search(r"\sin\s", f" {value} "):
					raise where.error(f"name the item: {{{{ for item in {value} }}}}")
				tag.block = "each"
				tag.attributes.append(("each", value, code, where))
			else:
				tag.block = "if"
				tag.attributes.append(("if", value, code, where))
			top.children.append(tag)
			self.stack.append(tag)
			return

		if keyword in ("/if", "/for"):
			if value:
				raise where.error(f"{{{{ {keyword} }}}} takes nothing")
			if opened is None:
				raise where.error(f"{{{{ {keyword} }}}} closes nothing")
			if top is not opened:
				raise where.error(
					f"{{{{ {keyword} }}}} closes {{{{ {opened.opener} }}}} from line {opened.where.line}, but <{top.name}> "
					f"from line {top.where.line} is still open inside it; a block wraps whole elements"
				)
			if keyword != f"/{opened.opener}":
				raise where.error(f"{{{{ {keyword} }}}} doesn't close {{{{ {opened.opener} }}}} from line {opened.where.line}; that needs {{{{ /{opened.opener} }}}}")
			self.stack.pop()
			return

		# {{ elif x }} or {{ else }}
		if opened is None:
			raise where.error(f"{{{{ {keyword} }}}} goes inside {{{{ if }}}}...{{{{ /if }}}}" + (" or {{ for }}...{{ /for }}" if keyword == "else" else ""))
		if top is not opened:
			raise where.error(f"{{{{ {keyword} }}}} belongs to {{{{ {opened.opener} }}}} from line {opened.where.line}, but <{top.name}> from line {top.where.line} is still open; close it first")
		if top.block == "else":
			raise where.error(f"{{{{ {opened.opener} }}}} from line {opened.where.line} already has an {{{{ else }}}}")
		if keyword == "elif":
			if top.opener == "for":
				raise where.error("{{ for }} can have an {{ else }} (shown when the list is empty), not {{ elif }}")
			if not value:
				raise where.error("{{ elif }} needs a condition: {{ elif loading }}")
		elif value:
			raise where.error("{{ else }} takes nothing; for another condition, use {{ elif x }}")
		self.stack.pop()
		tag = Tag("template", where)
		tag.opener = top.opener
		tag.block = keyword
		tag.attributes.append((keyword, value or None, code, where))
		self.stack[-1].children.append(tag)
		self.stack.append(tag)


	def open_tag(self):

		source = self.source
		start = self.pos
		match = TAG_START.match(source, start)
		tag = Tag(match.group(1), self.where(start, f"<{match.group(1)}>"))
		self.pos = match.end()

		while True:
			self.pos = SPACE.match(source, self.pos).end()
			if self.pos >= len(source):
				raise self.error(start, f"<{tag.name} is never closed with >")
			if source.startswith("/>", self.pos):
				self.pos += 2
				tag.self_closing = True
				break
			if source[self.pos] == ">":
				self.pos += 1
				break
			attribute = ATTRIBUTE.match(source, self.pos)
			if not attribute or attribute.end() == self.pos:
				raise self.error(self.pos, f"unexpected {source[self.pos]!r} in <{tag.name}>")
			name = attribute.group(1)
			value = attribute.group(2)
			if value is None:
				value = attribute.group(3)
			if value is None:
				value = attribute.group(4)
			where = self.where(self.pos, attribute.group(0))
			if tag.attribute(name) is not None:
				raise where.error(f"<{tag.name}> has {name} twice")
			tag.attributes.append((name, value, attribute.group(0), where))
			self.pos = attribute.end()

		parent = self.stack[-1]
		parent.children.append(tag)

		lower = tag.name.lower()
		if tag.self_closing or (not tag.component and lower in VOID_TAGS):
			return

		if not tag.component and (lower in RAW_TEXT or lower in ESCAPABLE_RAW_TEXT):
			end = re.compile(f"</\\s*{re.escape(tag.name)}\\s*>", re.IGNORECASE).search(source, self.pos)
			if end is None:
				raise TemplateError(f"{tag.where}: <{tag.name}> is never closed; add </{tag.name}>")
			self.stack.append(tag)
			self.text(self.pos, end.start(), raw=lower)
			self.stack.pop()
			self.pos = end.end()
			return

		self.stack.append(tag)


	def close_tag(self):

		source = self.source
		start = self.pos
		match = CLOSE_TAG.match(source, start)
		if not match:
			raise self.error(start, "malformed closing tag")

		name = match.group(1)
		tag = self.stack[-1]
		if name.lower() in VOID_TAGS and not is_component_name(name):
			raise self.error(start, f"</{name}>: <{name}> is a void element, with no closing tag")
		if tag is self.root:
			raise self.error(start, f"</{name}> closes nothing")
		if tag.block is not None:
			raise self.error(
				start, f"</{name}> comes before {{{{ /{tag.opener} }}}} for the {{{{ {tag.opener} }}}} from line "
				f"{tag.where.line}; a block wraps whole elements, so end it inside the element it starts in"
			)
		if name != tag.name and not (not tag.component and name.lower() == tag.name.lower()):
			raise self.error(start, f"</{name}> doesn't close <{tag.name}> from line {tag.where.line}, column {tag.where.col}")

		self.pos = match.end()
		self.stack.pop()


# Compiling ---------------------------------------------------------------------------------

# Op kinds; a str op is static HTML
VALUE, ATTRIBUTE_OP, CLASS, STYLE, EVENTS, IF, EACH, COMPONENT, SLOT = range(9)


class Definition:
	"""A component's markup: <TodoList class="x">...</TodoList> at the top level of a file."""

	__slots__ = ("name", "where", "ops", "root", "document")


	def __init__(self, name, where, ops, root, document=False):

		self.name = name
		self.where = where
		self.ops = ops
		self.root = root  # (static [(name, value)], bound [(name, function)], events, debounce)
		self.document = document  # its markup is a whole <html> document (a layout)


class Compiled:
	"""A parsed file: its component definitions, or, for a page, its ops."""


	def __init__(self, path):

		self.path = path
		self.definitions = {}
		self.ops = None
		self.document = False
		self.wrap = False  # Meteor-style <head> and <body> without <html>
		self.single = None  # a page that is one component (<Layout title="About">...</Layout>): its name


def parse_file(path, source=None):

	if source is None:
		with open(path, encoding="utf-8") as file:
			source = file.read()

	stats["parses"] += 1

	# {# domino #} at the top is a marker, not markup; keep the line count for errors
	marker = MARKER.match(source)
	if marker:
		source = "\n" * marker.group(0).count("\n") + source[marker.end():]

	nodes = Parser(source, path).parse()
	compiled = Compiled(path)

	top = [node for node in nodes if not (isinstance(node, Text) and node.blank())]
	first = top[0] if top else None
	if isinstance(first, Tag) and first.component and not is_page_path(path):
		for node in nodes:
			if isinstance(node, Text) and node.blank():
				continue
			if not (isinstance(node, Tag) and node.component):
				where = node.where if isinstance(node, Tag) else Parser(source, path).where(node.start) if isinstance(node, Text) else None
				shown = f"<{node.name}>" if isinstance(node, Tag) else "text"
				raise TemplateError(
					f"{where or shown_path(path)}: {shown} is outside a component definition. A file that defines "
					f"components (<{first.name}>...</{first.name}>) holds only definitions; put this inside one, "
					"or in a page template of its own"
				)
			if node.name in compiled.definitions:
				previous = compiled.definitions[node.name].where
				raise TemplateError(f"{node.where}: <{node.name}> is defined twice in this file (first at line {previous.line})")
			compiled.definitions[node.name] = compile_definition(node)
		return compiled

	_strip(nodes)
	compiled.ops = Compiler().nodes(nodes)
	tags = {node.name.lower() for node in nodes if isinstance(node, Tag)}
	compiled.document = any(isinstance(node, Raw) for node in nodes) or bool(tags & {"html", "head", "body"})
	compiled.wrap = "html" not in tags and bool(tags & {"head", "body"})
	if len(top) == 1 and isinstance(first, Tag) and first.component and not first.directive():
		compiled.single = first.name

	return compiled


def definitions_in(path):
	"""Names of the components a file defines (cached like the file itself)."""

	compiled = load(path, check=True)

	return list(compiled.definitions)


def _strip(nodes):
	"""Drop the whitespace at the start and end of a definition or a page."""

	for index, strip in ((0, str.lstrip), (-1, str.rstrip)):
		while nodes and isinstance(nodes[index], Text):
			parts = nodes[index].parts
			if parts and isinstance(parts[index], str):
				parts[index] = strip(parts[index])
				if not parts[index]:
					parts.pop(index)
			if parts:
				break
			nodes.pop(index)


def compile_definition(tag):

	if tag.self_closing:
		raise TemplateError(
			f"{tag.where}: <{tag.name} /> at the top level of a file defines {tag.name}, but has no markup. "
			f"Wrap the markup: <{tag.name}>...</{tag.name}>. To show {tag.name} on a page, put it inside an "
			"element of a page template"
		)
	if tag.directive():
		raise TemplateError(f"{tag.where}: <{tag.name} {tag.directive()}> defines {tag.name}; each/if go on the elements inside it")

	children = list(tag.children)
	_strip(children)

	# <Layout><html lang="en">...</html></Layout>: the component is the whole document, its element
	# the <html> (as with as="html"), so a page that wraps itself in <Layout> is a whole page
	attributes = list(tag.attributes)
	document = False
	only = [node for node in children if not (isinstance(node, Text) and node.blank())]
	if len(only) == 1 and isinstance(only[0], Tag) and only[0].name.lower() == "html":
		html = only[0]
		if tag.attribute("as") is not None:
			raise tag.where.error(f"<{tag.name}>'s markup is an <html> document, so it is the <html>; leave out as=")
		if html.directive():
			raise html.where.error(f"<html {html.directive()}>: a document is shown whole; put each/if on the elements inside it")
		attributes += html.attributes
		children = list(html.children)
		_strip(children)
		document = True

	compiler = Compiler()
	static, bound, events, debounce, element = [], [], [], None, "html" if document else None
	for name, value, text, where in attributes:
		if name == "as":
			# <Sidebar as="aside">: the component's element is an <aside>
			if not value or not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", value) or is_component_name(value):
				raise where.error("as= names the HTML element the component is, like as=\"aside\"")
			element = value
		elif name.startswith(":"):
			raise where.error(OLD_BINDING.format(name=name[1:], value=value))
		elif name.startswith("on-"):
			events.append((name[3:].lower(), compiler.handler(value, where)))
		elif name == "debounce":
			debounce = compiler.debounce(value, where)
		elif value is not None and "{{" in value:
			bound.append((name, compiler.attribute(value, where, name)))
		else:
			compiler.literal(value, where)
			static.append((name, True if value is None else unescape(value)))

	return Definition(tag.name, tag.where, compiler.nodes(children), (static, bound, events, debounce, element), document)


class Compiler:


	def nodes(self, nodes, raw=None):

		ops = []
		index = 0
		while index < len(nodes):
			node = nodes[index]
			if isinstance(node, Text):
				self.text(node, ops, raw)
				index += 1
				continue
			if isinstance(node, Raw):
				ops.append(node.text)
				index += 1
				continue

			directive = node.directive()
			if directive in ("elif", "else"):
				raise node.where.error(f"<{node.name} {directive}> needs an element with if= (or each=) right before it")
			if directive is None:
				self.element(node, ops)
				index += 1
				continue

			# An element with each/if takes the line break before it along; a block's lines are gone
			lead = "" if node.block is not None else _lead(ops)
			if directive == "each":
				names, iterable, where = self.each(node)
				condition = node.attribute("if")
				condition = condition and self.value(condition[1], condition[3])
				body = self.body(node)
				index, branches = self.chain(nodes, index, allowed=("else",))
				empty = branches[0] if branches else None
				ops.append((EACH, names, iterable, condition, lead, body, empty, where))
			else:
				condition = node.attribute("if")
				branches = [(self.value(condition[1], condition[3]), lead, self.body(node))]
				index, more = self.chain(nodes, index, allowed=("elif", "else"))
				ops.append((IF, branches + more))

		return _merge(ops)


	def chain(self, nodes, index, allowed):
		"""The elif/else siblings after nodes[index] -> (index after them, [(condition, lead, ops)])."""

		branches = []
		while True:
			following = index + 1
			while following < len(nodes) and isinstance(nodes[following], Text) and nodes[following].blank():
				following += 1
			node = nodes[following] if following < len(nodes) else None
			directive = node.directive() if isinstance(node, Tag) else None
			if directive not in ("elif", "else") or (branches and branches[-1][0] is None):
				return index + 1, branches
			if directive not in allowed:
				raise node.where.error(f"<{node.name} {directive}> can't follow each=; only else (shown when the list is empty) can")
			lead = ""
			between = nodes[following - 1] if following - 1 > index else None
			if between is not None:
				text = "".join(between.parts)
				match = LEAD.search(text)
				lead = text[match.start():] if match else ""
			if directive == "elif":
				condition = node.attribute("elif")
				branches.append((self.value(condition[1], condition[3]), lead, self.body(node)))
			else:
				if node.attribute("else")[1] is not None:
					raise node.where.error("else takes no value; use elif=\"...\" for another condition")
				branches.append((None, lead, self.body(node)))
			index = following


	def each(self, node):

		_, value, _, where = node.attribute("each")
		if value is None:
			raise where.error("each needs a value: each=\"item in items\"")
		try:
			names, expression = parse_each(value)
		except TemplateError as error:
			raise TemplateError(f"{where}: {error}") from None
		where.text = f"each=\"{value}\""

		return names, compile_expression(expression, where), where


	def body(self, node):
		"""The ops of an element with a directive; <template each=...> renders only its content."""

		ops = []
		# A block's content is kept as written (the lines of its {{ }} tags are already gone)
		if node.block is not None:
			return self.nodes(list(node.children))
		if node.name == "template" and not node.component:
			if any(name not in DIRECTIVES for name, *_ in node.attributes):
				raise node.where.error("<template each/if> only renders its content, so it takes no other attributes")
			# Its content is laid out like the element's own: each copy on lines of its own
			children = list(node.children)
			_strip(children)
			return self.nodes(children)
		self.element(node, ops, skip=DIRECTIVES)

		return _merge(ops)


	def value(self, text, where, mode="value"):

		if text is None:
			raise where.error(f"{where.text.split('=')[0]} needs a value")
		try:
			expression = parse_expression(text)
		except TemplateError as error:
			raise TemplateError(f"{where}: {error}") from None

		return compile_expression(expression, where, mode)


	def handler(self, text, where):

		if text is None:
			raise where.error("an event needs a handler: on-click=\"increment\" or on-click=\"remove(item)\"")

		return self.value(text, where, mode="handler")


	def debounce(self, text, where):

		try:
			return int(text)
		except (TypeError, ValueError):
			raise where.error("debounce takes a number of milliseconds, like debounce=\"250\"") from None


	def attribute(self, value, where, name=None):
		"""A function giving an attribute's value. Just "{{ x }}" gives x itself (True writes the bare
		attribute, False and None leave it out, and a component gets the object); anything else,
		text with values and {{ if }} blocks in it, gives the text. In class, a dict or list value
		gives the names that are on ({"done": True} -> done); in style, a dict gives declarations."""

		single = SINGLE_VALUE.fullmatch(value)
		if single and not BLOCK.match(single.group(1)):
			return self.value(single.group(1), where)

		parts = attribute_parts(value, where)
		show = {"class": lambda value: " ".join(class_names(value)), "style": style_text}.get(name, str)

		def text(context):
			out = []
			_attribute_text(parts, context, out, show)
			return "".join(out)

		return text


	def literal(self, value, where):

		if value is not None and "{{" in value:
			name = where.text.split("=")[0]
			raise where.error(
				f"attributes are written as they are, so {{{{ }}}} doesn't work in them; bind the attribute "
				f"instead: :{name}=\"helper\", with a helper method that returns the value"
			)


	def text(self, node, ops, raw):

		for part in node.parts:
			if isinstance(part, str):
				ops.append(part)
			else:
				where, expression = part
				ops.append((VALUE, compile_expression(expression, where), raw))


	def element(self, node, ops, skip=()):

		if node.component:
			ops.append(self.component(node, skip))
			return

		if node.name == "slot":
			if any(name not in skip for name, *_ in node.attributes):
				raise node.where.error("<slot> takes no attributes: it's where the children given to the component go")
			ops.append((SLOT, self.nodes(node.children)))
			return

		ops.append(f"<{node.name}")
		events, debounce = [], None
		bound = {}
		for name, value, text, where in node.attributes:
			if name in skip:
				continue
			if name.startswith("on-"):
				events.append((name[3:].lower(), self.handler(value, where)))
			elif name == "debounce" and any(other.startswith("on-") for other, *_ in node.attributes):
				debounce = self.debounce(value, where)
			elif name.startswith(":"):
				raise where.error(OLD_BINDING.format(name=name[1:], value=value))
			elif name in DIRECTIVES:
				raise where.error(DIRECTIVE_ATTRIBUTE.format(name=name))

		for name, value, text, where in node.attributes:
			if name in skip or name.startswith("on-") or name == "debounce" and events:
				continue
			if value is not None and "{{" in value:
				# class="task {{ if done }}done{{ /if }}", href="/polls/{{ poll._id }}", disabled="{{ at_zero }}"
				function = self.attribute(value, where, name)
				if name in ("class", "style"):
					ops.append((CLASS if name == "class" else STYLE, "", function))
				else:
					ops.append((ATTRIBUTE_OP, name, function))
			else:
				self.literal(value, where)
				ops.append(f" {text}")

		if events:
			ops.append((EVENTS, events, debounce))

		ops.append(">")

		lower = node.name.lower()
		if lower in VOID_TAGS:
			return

		raw = lower if lower in RAW_TEXT or lower in ESCAPABLE_RAW_TEXT else None
		ops.extend(self.nodes(node.children, raw))
		ops.append(f"</{node.name}>")


	def component(self, node, skip):

		static, bound, events, debounce = [], [], [], None
		for name, value, text, where in node.attributes:
			if name in skip:
				continue
			if name.startswith(":"):
				raise where.error(OLD_BINDING.format(name=name[1:], value=value))
			elif name.startswith("on-"):
				events.append(("on_" + prop_name(name[3:].lower()), self.handler(value, where)))
			elif name == "debounce":
				debounce = self.debounce(value, where)
			elif name in DIRECTIVES:
				raise where.error(DIRECTIVE_ATTRIBUTE.format(name=name))
			elif value is not None and "{{" in value:
				# items="{{ items }}" passes the list itself; heading="Hi {{ name }}" a string
				bound.append((prop_name(name), self.attribute(value, where, name)))
			else:
				self.literal(value, where)
				static.append((prop_name(name), True if value is None else unescape(value)))

		children = None
		if node.children and not all(isinstance(child, Text) and child.blank() for child in node.children):
			# Placed where the component's <slot /> is, without the space around it here
			nodes = list(node.children)
			_strip(nodes)
			children = self.nodes(nodes)

		return (COMPONENT, node.name, node.where, static, bound, events, debounce, children, {})


def attribute_parts(value, where):
	"""An attribute's text, values and {{ if }} blocks -> [str | (VALUE, function) | (IF, [(condition, parts)])]."""

	root = []
	current = root
	stack = []  # (the if's branches, the parts the if is in)
	pos = 0
	for match in VALUE_TAG.finditer(value):
		if match.start() > pos:
			current.append(unescape(value[pos:match.start()]))
		code = match.group(1)
		block = BLOCK.match(code)
		if block is None:
			try:
				expression = parse_expression(code)
			except TemplateError as error:
				raise TemplateError(f"{where}: {error}") from None
			current.append((VALUE, compile_expression(expression, where)))
		else:
			keyword, rest = block.group(1).replace(" ", ""), block.group(2).strip()
			if keyword in ("for", "/for"):
				raise where.error("{{ for }} doesn't go inside an attribute; a helper can build the value")
			if keyword == "if":
				branches = [(Compiler().value(rest, where), [])]
				current.append((IF, branches))
				stack.append((branches, current))
				current = branches[-1][1]
			elif not stack:
				raise where.error(f"{{{{ {keyword} }}}} has no {{{{ if }}}} before it in this attribute")
			elif keyword == "/if":
				current = stack.pop()[1]
			else:
				branches = stack[-1][0]
				if branches[-1][0] is None:
					raise where.error("this {{ if }} already has an {{ else }}")
				branches.append((Compiler().value(rest, where) if keyword == "elif" else None, []))
				current = branches[-1][1]
		pos = match.end()
	if stack:
		raise where.error("an {{ if }} in this attribute is never closed with {{ /if }}")
	if pos < len(value):
		current.append(unescape(value[pos:]))

	return root


def _attribute_text(parts, context, out, show=str):

	for part in parts:
		if type(part) is str:
			out.append(part)
		elif part[0] == VALUE:
			value = part[1](context)
			if value is not None and value is not False:
				out.append(show(value))
		else:
			for condition, body in part[1]:
				if condition is None or condition(context):
					_attribute_text(body, context, out, show)
					break


def prop_name(name):

	# The keyword the component gets: aria-label -> aria_label, class -> class_ (extra classes)
	if name == "class":
		return "class_"

	return name.replace("-", "_")


def _lead(ops):
	"""Take the line break and indentation before an element with each/if, so each item gets
	its own line and an element left out leaves no empty line."""

	if ops and type(ops[-1]) is str:
		match = LEAD.search(ops[-1])
		if match:
			lead = ops[-1][match.start():]
			ops[-1] = ops[-1][:match.start()]
			if not ops[-1]:
				ops.pop()
			return lead

	return ""


def _merge(ops):

	merged = []
	for op in ops:
		if type(op) is str:
			if not op:
				continue
			if merged and type(merged[-1]) is str:
				merged[-1] += op
				continue
		merged.append(op)

	return merged


# Loading -----------------------------------------------------------------------------------

def load(path, check=True):
	"""The compiled file, parsed once; with `check`, parsed again if it changed since."""

	cached = _compiled.get(path)
	if cached is not None and not check:
		return cached[1]

	mtime = os.path.getmtime(path)
	if cached is not None and cached[0] == mtime:
		return cached[1]

	compiled = parse_file(path)
	_compiled[path] = (mtime, compiled)

	return compiled


def _checking():
	"""Whether files are checked for changes: while debugging (or TEMPLATES_AUTO_RELOAD)."""

	from .templates import _app

	try:
		app = _app()
	except RuntimeError:
		return True

	return bool(app.debug or app.config.get("TEMPLATES_AUTO_RELOAD"))


def forget():
	"""Hot reloading: parse files again and look classes up again."""

	_compiled.clear()
	_formats.clear()
	_known.clear()


# Rendering ---------------------------------------------------------------------------------

class Context:
	"""What a render reads: loop variables (`local`), the template's names (`lookup`), the slot's
	content, and where events go (the page, and the component whose render this is)."""

	__slots__ = ("local", "lookup", "slot", "page", "frame", "prefix")


	def __init__(self, local, lookup, slot=None, parent=None):

		self.local = local
		self.lookup = lookup
		self.slot = slot
		if parent is not None:
			self.page, self.frame, self.prefix = parent.page, parent.frame, parent.prefix
			return

		self.page = Page.current()
		# Events are numbered per component, as Element.bind does, so they keep their ids
		# across re-renders and go when the component is re-rendered
		stack = render_stack()
		self.frame = stack[-1] if stack else None
		self.prefix = f"event-{self.frame[0].id()}-" if stack else None


	def child(self, local):

		return Context(local, self.lookup, self.slot, self)


def run(ops, context, out):

	for op in ops:
		if type(op) is str:
			out.append(op)
			continue
		kind = op[0]
		if kind == VALUE:
			_value(op[1](context), op[2], out)
		elif kind == EACH:
			_each(op, context, out)
		elif kind == IF:
			for condition, lead, body in op[1]:
				if condition is None or condition(context):
					if lead:
						out.append(lead)
					run(body, context, out)
					break
		elif kind == ATTRIBUTE_OP:
			value = op[2](context)
			if value is True:
				out.append(f" {op[1]}")
			elif value is not None and value is not False:
				out.append(f" {op[1]}=\"{_escape(value)}\"")
		elif kind == CLASS:
			names = op[1].split() + class_names(op[2](context))
			if names:
				out.append(f" class=\"{_escape(' '.join(names))}\"")
		elif kind == STYLE:
			style = style_text(op[2](context))
			text = "; ".join(part for part in (op[1].strip().rstrip(";"), style) if part)
			if text:
				out.append(f" style=\"{_escape(text)}\"")
		elif kind == EVENTS:
			out.append(_events(op[1], op[2], context))
		elif kind == COMPONENT:
			out.append(_component(op, context))
		elif kind == SLOT:
			if context.slot:
				for item in context.slot:
					out.append(item if isinstance(item, (Element, Markup)) else _escape(item))
			else:
				run(op[1], context, out)


def _escape(value):
	"""markupsafe.escape as a str, faster for the plain strings most values are."""

	if type(value) is str:
		if "&" in value or "<" in value or ">" in value or '"' in value or "'" in value:
			return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&#34;").replace("'", "&#39;")
		return value

	return str(escape(value))


def _value(value, raw, out):

	if value is None or value is False:
		return

	if raw is None:
		if isinstance(value, Markup):
			out.append(str(value))
		elif isinstance(value, Element):
			out.append(value)
		elif isinstance(value, type) and issubclass(value, Element):
			out.append(value())
		elif isinstance(value, (list, tuple, types.GeneratorType)):
			for item in value:
				_value(item, raw, out)
		else:
			out.append(_escape(value))
	elif raw == "script":
		# Values go into scripts as JSON, which can't end the script early
		out.append(script_json(value))
	elif raw == "style":
		out.append(str(value).replace("<", "\\3c "))
	else:
		out.append(_escape(value))


def _each(op, context, out):

	_, names, iterable, condition, lead, body, empty, where = op
	items = iterable(context)
	shown = False
	if items:
		single = names[0] if len(names) == 1 else None
		for item in items:
			local = dict(context.local)
			if single is not None:
				local[single] = item
			else:
				try:
					values = tuple(item)
				except TypeError:
					values = None
				if values is None or len(values) != len(names):
					raise where.error(f"can't unpack {item!r} into {', '.join(names)}")
				local.update(zip(names, values))
			inner = context.child(local)
			if condition is not None and not condition(inner):
				continue
			shown = True
			if lead:
				out.append(lead)
			run(body, inner, out)

	if not shown and empty is not None:
		if empty[1] or lead:
			out.append(empty[1] or lead)
		run(empty[2], context, out)


def class_names(value):

	if value is None or value is False:
		return []
	if isinstance(value, str):
		return value.split()
	if isinstance(value, dict):
		return [name for name, on in value.items() if on]
	if isinstance(value, (list, tuple, set)):
		names = []
		for item in value:
			names.extend(class_names(item))
		return names

	return str(value).split()


def style_text(value):

	if value is None or value is False:
		return ""
	if isinstance(value, dict):
		return "; ".join(
			f"{name.replace('_', '-')}: {css}" for name, css in value.items() if css is not None and css is not False
		)

	return str(value).strip().rstrip(";")


def _events(events, debounce, context):

	frame = context.frame
	page = context.page

	ids = []
	marks = []
	for name, handler in events:
		callback = handler(context)
		if not callable(callback):
			raise TemplateError(f"on-{name}: {callback!r} isn't a handler")
		# Numbered per component, as Element._event_id does
		if frame is not None:
			frame[1] += 1
			event_id = f"{context.prefix}{frame[1]}-{name}"
			page.register(event_id, frame[0], callback)
		else:
			event_id = f"event-{uuid.uuid4()}-{name}"
			page.register(event_id, getattr(callback, "__self__", None), callback)
		ids.append(event_id)
		if debounce:
			marks.append(f" data-debounce-{name}=\"{int(debounce)}\"")

	return f" data-event-id=\"{' '.join(ids)}\"" + "".join(marks)


def _component(op, context):

	_, name, where, static, bound, events, debounce, children, cache = op

	cls = context.lookup.component(name, where, cache)

	kwargs = dict(static)
	for key, value in bound:
		kwargs[key] = value(context)
	for key, handler in events:
		kwargs[key] = handler(context)
	if events and debounce:
		kwargs["debounce"] = debounce

	try:
		element = cls(**kwargs)
	except TemplateError:
		raise
	except TypeError as error:
		raise where.error(f"<{name}> couldn't be made: {error}") from error

	if not isinstance(element, Element):
		raise where.error(f"<{name}> made {element!r}, not a component")

	# What's between <Card> and </Card> goes where Card's template has <slot />. It's rendered now,
	# so its events belong to this component, like the rest of its markup
	if children is not None:
		out = []
		run(children, context, out)
		element.set_children([Fragment(_join(out))])

	return element


def _join(out):

	chunks = []
	for item in out:
		if type(item) is str and chunks and type(chunks[-1]) is str:
			chunks[-1] += item
		else:
			chunks.append(item)

	return chunks


class Fragment(Element):
	"""Rendered template markup: HTML strings, and the components inside rendered in place.
	Components holding one render it exactly as written (see Element._render)."""

	verbatim = True


	def __init__(self, chunks):

		super().__init__("")

		self.chunks = chunks
		# For the walks that find a page's components (events, refresh, hot reloading)
		self.__children__ = [chunk for chunk in chunks if isinstance(chunk, Element)]


	def _render(self, level=0, indent=4):

		html = render_chunks(self.chunks)

		# In a parent that lays out its children one per line (Python-built ones)
		if indent:
			html += "\n"

		return html


def render_chunks(chunks):

	parts = []
	for chunk in chunks:
		if isinstance(chunk, str):
			parts.append(chunk)
			continue
		try:
			parts.append(chunk._render(0, ""))
		except Exception as error:
			note_render_error(error, chunk)
			raise

	return "".join(parts)


# Names -------------------------------------------------------------------------------------

# class name -> [classes], from the live subclasses of Element (see known_classes)
_known = {}

# Component class -> names a template can read from it (besides its instance's attributes)
_class_names = {}


def component_names(cls):

	names = _class_names.get(cls)
	if names is None:
		names = set()
		for base in cls.__mro__:
			if base is object or base is Element or base.__module__ == "domino.tags":
				continue
			names.update(name for name in vars(base) if not name.startswith("_"))
		names -= {"render", "init", "css", "live", "optimistic", "optimistic_states", "client"}
		_class_names[cls] = names

	return names


class Lookup:
	"""Where a template's names come from: a component, or a page template's context."""


	def __init__(self, path, namespaces, component=None, context=None):

		self.path = path
		self.namespaces = namespaces  # where classes are looked up first
		self.element = component
		self.context = context


	def __call__(self, name, where):

		element = self.element
		if element is not None:
			values = element.__dict__
			if name in values and not name.startswith("_") and name not in ELEMENT_NAMES:
				return values[name]
			if name in component_names(type(element)):
				return getattr(element, name)
			if isinstance(element, MarkupComponent) and not name.startswith("_") and name not in BUILTINS:
				return None
		elif name in self.context:
			return self.context[name]

		if name in BUILTINS:
			return BUILTINS[name]

		raise where.error(self.missing(name), name, self.available())


	def missing(self, name):

		if self.element is not None:
			return f"{type(self.element).__name__} has no {name!r}"

		return f"no {name!r} in the template's context (template(\"...\", {name}=...))"


	def available(self):

		if self.element is None:
			return list(self.context)

		names = component_names(type(self.element))
		names |= {name for name in self.element.__dict__ if not name.startswith("_") and name not in ELEMENT_NAMES}

		return names


	def component(self, name, where, cache):

		for namespace in self.namespaces:
			value = namespace.get(name)
			if isinstance(value, type) and issubclass(value, Element):
				return value

		# Found once per tag; again if its module was imported again since (hot reloading, tests)
		cls = cache.get("class")
		if cls is None or getattr(sys.modules.get(cls.__module__), cls.__name__, None) is not cls:
			cls = cache["class"] = find_class(name, where, self.path)

		return cls


def known_classes():
	"""Component classes by name: the app's Element subclasses alive now (one per module and
	name, the newest when a module was hot reloaded)."""

	if _known:
		return _known

	found = {}
	stack = list(Element.__subclasses__())
	seen = set()
	while stack:
		cls = stack.pop()
		if cls in seen:
			continue
		seen.add(cls)
		stack.extend(cls.__subclasses__())
		if cls.__module__.split(".")[0] == "domino":
			continue
		key = (cls.__module__, cls.__qualname__)
		current = found.get(key)
		module = sys.modules.get(cls.__module__)
		if current is None or getattr(module, cls.__name__, None) is cls:
			found[key] = cls

	for cls in found.values():
		_known.setdefault(cls.__name__, []).append(cls)

	return _known


def app_classes(name, mine=False):
	"""The component classes called `name`: those of the app's own modules if any (another app, or
	a test module, may have one of the same name in this process), else (unless `mine`) any."""

	classes = known_classes().get(name) or []
	finder = _finder()
	if finder is None:
		return classes

	root = finder.root + os.sep
	own = [cls for cls in classes if (getattr(sys.modules.get(cls.__module__), "__file__", None) or "").startswith(root)]

	return own if own or mine else classes


def find_class(name, where, path):

	# Classes defined since they were last listed count too (it's once per tag)
	_known.clear()
	classes = app_classes(name, mine=True)

	if not classes:
		# Defined in a file next to a module of the same name (components/card.html and
		# components/card.py) that nothing has imported yet
		if _import_definer(name):
			_known.clear()
		classes = app_classes(name, mine=True)

	if not classes:
		# Markup without a class (layouts/layout.html defining <Layout>, say): a component of its
		# own, before any class of that name another app (or test) has
		finder = _finder()
		defined = finder.current_definitions().get(name) if finder is not None else None
		if defined:
			return markup_component(name, defined[0])
		classes = app_classes(name)

	if not classes:
		names = set(known_classes())
		finder = _finder()
		if finder is not None:
			names |= set(finder.definitions)
		raise where.error(
			f"<{name}> isn't a component Domino knows: define class {name} in a module of the app "
			"(and import it, or put it next to its template)",
			name, names
		)

	if len(classes) > 1:
		modules = ", ".join(sorted(f"{cls.__module__}.{cls.__qualname__}" for cls in classes))
		raise where.error(f"<{name}> could be any of {modules}; import the one you mean in the module next to {shown_path(path)}")

	return classes[0]


from .tags import div as _div


class MarkupComponent(_div):
	"""A component defined only in a template, with no class of its own: what it's given
	(<Layout title="About">) are its values, and a name it isn't given shows nothing."""

	_domino_base = True


	def configure(self, **kwargs):

		for key in list(kwargs):
			if key not in ("class_", "id", "style", "debounce") and not key.startswith(("on_", "data_", "aria_")):
				self.__dict__[key] = kwargs.pop(key)

		return super().configure(**kwargs)


_markup_components = {}


def markup_component(name, path):
	"""The class for <name> when only its markup exists (at `path`), made once per file."""

	key = (name, os.path.abspath(path))
	cls = _markup_components.get(key)
	if cls is None:
		cls = _markup_components[key] = type(name, (MarkupComponent,), {"_domino_definition": key[1], "__module__": __name__})

	return cls


def _import_definer(name):

	finder = _finder()
	if finder is None:
		return False

	# The modules next to its definition, then those next to every definition (a class with a
	# render() has none, but often shares a module), then components/<snake_case name>.py
	definitions = finder.current_definitions()
	paths = list(definitions.get(name, ()))
	for found in definitions.values():
		paths += [path for path in found if path not in paths]
	from .templates import snake_case
	paths.append(os.path.join(finder.root, "components", f"{snake_case(name)}.html"))

	# Files already imported, under whatever name
	files = {os.path.abspath(getattr(module, "__file__", None) or "") for module in list(sys.modules.values())}

	imported = False
	for path in paths:
		module = _module_for(path, finder.root)
		source = os.path.abspath(os.path.splitext(path)[0] + ".py")
		if not module or source in files:
			continue
		files.add(source)
		loaded = sys.modules.get(module)
		if loaded is None and not _importable(module, finder.root):
			# Not importable by its name from here (the app's folder isn't on the import path), or
			# the name would find another app's package (tests run several apps in one process)
			loaded = False
		if loaded is not None:
			module = f"domino_app_modules_{abs(hash(finder.root))}.{module}"
			if module in sys.modules:
				continue
			spec = importlib.util.spec_from_file_location(module, source)
			loaded = importlib.util.module_from_spec(spec)
			sys.modules[module] = loaded
			spec.loader.exec_module(loaded)
		else:
			try:
				loaded = importlib.import_module(module)
			except ModuleNotFoundError as error:
				# The app's folder isn't importable as packages (not on the path): nothing to find
				if error.name and module.startswith(error.name):
					continue
				raise
		imported = True
		if any(cls.__name__ == name for cls in vars(loaded).values() if isinstance(cls, type)):
			return True

	return imported


def _importable(module, root):
	"""Whether `import module` finds the app's own file: its folder is on the import path and the
	package the name starts with isn't another folder's."""

	if os.path.abspath(root) not in [os.path.abspath(path) for path in sys.path if path]:
		return False

	top = sys.modules.get(module.split(".")[0])
	if top is None:
		return True
	paths = [getattr(top, "__file__", None) or ""] + list(getattr(top, "__path__", None) or [])

	return any(os.path.abspath(path).startswith(os.path.abspath(root) + os.sep) for path in paths if path)


def _module_for(path, root):
	"""The module next to a template (components/card.html -> components.card), if there's one."""

	stem = os.path.splitext(path)[0]
	if not os.path.isfile(stem + ".py"):
		return None

	relative = os.path.relpath(stem, root)
	parts = relative.split(os.sep)
	if relative.startswith("..") or not all(part.isidentifier() for part in parts):
		return None

	return ".".join(parts)


def warn_unused():
	"""Once per scan of the app's files: warn about definitions no component class is named after
	but one is named much like (a typo, or a class renamed). A definition with no class like it is
	a component that is only markup (see MarkupComponent). Modules next to them are imported to know."""

	finder = _finder()
	if finder is None or finder.warned:
		return
	definitions = finder.current_definitions()
	finder.warned = True

	from .templates import _app

	for name, paths in sorted(definitions.items()):
		if app_classes(name):
			continue
		try:
			_import_definer(name)
		except Exception:
			pass
		_known.clear()
		if not app_classes(name):
			close = difflib.get_close_matches(name, list(known_classes()), n=1)
			if close:
				_app().logger.warning(
					"Domino: %s defines <%s>, but no component class is called %s (did you mean %s?); "
					"it's used as markup only",
					", ".join(shown_path(path) for path in paths), name, name, close[0]
				)


def _finder():

	from .templates import _app

	try:
		return getattr(_app(), "template_finder", None)
	except RuntimeError:
		return None


# Components and pages ----------------------------------------------------------------------

def definition_for(cls, path):
	"""The definition of `cls` in the file at `path`, or a TemplateError saying what's wrong."""

	compiled = load(path, _checking())
	name = cls.__name__
	definition = compiled.definitions.get(name)
	if definition is not None:
		finder = _finder()
		others = [other for other in (finder.definitions.get(name, ()) if finder else ()) if other != path]
		module_file = getattr(sys.modules.get(cls.__module__), "__file__", None) or ""
		next_to_module = os.path.splitext(os.path.abspath(module_file))[0] == os.path.splitext(path)[0]
		if others and not next_to_module:
			files = "\n".join(f"    {shown_path(other)}" for other in [path] + others)
			raise TemplateError(f"<{name}> is defined in several files; keep one (or put it next to {cls.__module__}'s file, which then wins):\n{files}")
		return definition

	if compiled.ops is not None:
		raise TemplateError(
			f"{shown_path(path)}: its markup isn't wrapped in <{name}>...</{name}>. A component's template "
			f"is inside a tag named after its class: <{name}> at the top level of the file, the markup inside"
		)

	defined = ", ".join(sorted(compiled.definitions)) or "nothing"
	close = difflib.get_close_matches(name, list(compiled.definitions), n=1)
	hint = f" Did you mean to name <{close[0]}> {name}?" if close else ""
	raise TemplateError(
		f"{shown_path(path)} defines {defined}, not {name}: add <{name}>...</{name}> for the class "
		f"{cls.__module__}.{name}, or give it a render() method.{hint}"
	)


def defines_document(name):
	"""Whether the component called `name` is defined as a whole <html> document (a layout)."""

	finder = _finder()
	if finder is None:
		return False

	for path in finder.current_definitions().get(name, ()):
		definition = load(path, _checking()).definitions.get(name)
		if definition is not None and definition.document:
			return True

	return False


def render_component(element, path):
	"""render() for a component defined in a Domino template: its markup, as one Fragment."""

	cls = type(element)
	definition = definition_for(cls, path)
	warn_unused()

	# What a parent put inside it (<Card>...</Card>, or Card() [...]) is kept for its <slot />, since
	# rendering replaces the children
	slot = element.__dict__.get("_domino_slot")
	if slot is None:
		slot = element.__dict__["_domino_slot"] = list(element.content_root.__children__)

	module = sys.modules.get(cls.__module__)
	lookup = Lookup(path, [vars(module)] if module else [], component=element)
	context = Context({}, lookup, slot)

	_root(element, definition, context)

	out = []
	run(definition.ops, context, out)

	return [Fragment(_join(out))]


def _root(element, definition, context):
	"""The defining tag's attributes go on the component's element; what the Python side set wins,
	and classes add up (the template's come first)."""

	static, bound, events, debounce, tag = definition.root
	attributes = element.__attributes__

	# as="aside" picks the element; a class that sets its own `tag` must agree
	if tag is not None:
		declared = _declared_tag(type(element))
		if declared is not None and declared != tag:
			raise definition.where.error(
				f"<{definition.name} as=\"{tag}\"> makes it an <{tag}>, but the class {type(element).__name__} "
				f"sets tag = \"{declared}\"; keep one of them"
			)
		element.__tag__ = tag

	# Undo what the last render set, so a bound attribute that's now None goes
	previous = element.__dict__.get("_domino_root") or {}
	for key, value in previous.items():
		if attributes.get(key) is value:
			del attributes[key]

	applied = {}
	values = list(static) + [(name, function(context)) for name, function in bound]
	classes = []
	for name, value in values:
		if name == "class":
			classes.extend(class_names(value))
			continue
		key = name.replace("-", "_")
		if key == "style" and isinstance(value, dict):
			value = style_text(value)
		if key not in attributes and value is not None and value is not False:
			attributes[key] = applied[key] = value
	if classes and "class" not in attributes:
		attributes["class"] = applied["class"] = " ".join(classes)
	element.__dict__["_domino_root"] = applied

	for name, handler in events:
		element.bind(name, handler(context), debounce=debounce)


def _declared_tag(cls):
	"""The tag name a component class sets itself (tag = "section"), if any."""

	for base in cls.__mro__:
		if base.__module__.split(".")[0] == "domino":
			return None
		value = vars(base).get("tag")
		if isinstance(value, str):
			return value

	return None


def whole_page(result):
	"""`result`, or, for a component whose markup is a whole <html> document (a layout returned
	from page() or a route: Layout(title="About") [...]), that component as the page."""

	if not isinstance(result, Element) or isinstance(result, (DominoTemplate, WholePage)):
		return result

	from .templates import paired_template, template_format

	cls = type(result)
	path = paired_template(cls)
	if not path or template_format(path) != "components":
		return result
	definition = load(path, _checking()).definitions.get(cls.__name__)
	if definition is None or not definition.document:
		return result

	return WholePage(result)


class WholePage(Element):
	"""A document component as the page: its <html>, with the doctype and Domino's script."""

	verbatim = True
	is_document = True


	def __init__(self, component):

		super().__init__("")

		self.component = component
		self.__children__ = [component]


	def _render(self, level=0, indent=4):

		styles = current_styles()
		if styles is None:
			with collect_styles() as styles:
				html = self._render(level, indent)
			return styles.finish(html)

		html = "<!DOCTYPE html>\n" + self.component._render(level, indent)

		if self.__attributes__:
			from .templates import _as_page
			return _as_page(html, self.__attributes__)

		return html


class DominoTemplate(Element):
	"""template("home.html"): a page, or part of one, written as a Domino template."""

	verbatim = True


	def __init__(self, path, context, namespace=None, slot=None):

		super().__init__("")

		self.path = path
		self.context = context
		self.namespace = namespace or {}
		self.slot = slot  # for a layout: the page, where it has <slot />
		# Found by the walks over a page's elements (events, hot reloading) before it renders
		self.__children__ = [item for item in slot or () if isinstance(item, Element)]


	@property
	def is_document(self):

		compiled = load(self.path, _checking())

		return compiled.document or (compiled.single is not None and defines_document(compiled.single))


	def _render(self, level=0, indent=4):

		styles = current_styles()
		if styles is None:
			with collect_styles() as styles:
				html = self._render(level, indent)
			return styles.finish(html)

		compiled = load(self.path, _checking())
		if compiled.ops is None:
			names = ", ".join(compiled.definitions)
			raise TemplateError(
				f"{shown_path(self.path)} defines components ({names}), so it isn't a page; show them from a "
				f"page template (<{next(iter(compiled.definitions))} />) or a page's page() function"
			)

		warn_unused()
		lookup = Lookup(self.path, [self.context, self.namespace], context=self.context)
		out = []
		run(compiled.ops, Context({}, lookup, self.slot), out)
		chunks = _join(out)
		self.__children__ = [chunk for chunk in chunks if isinstance(chunk, Element)]
		html = render_chunks(chunks)

		if self.is_document:
			if compiled.wrap:
				html = f"<html>\n{html}\n</html>"
			if not html.lstrip()[:2].startswith("<!"):
				html = f"<!DOCTYPE html>\n{html}"

		# Returned from a route, the template is the page: it needs the page id and core.js
		if self.__attributes__:
			from .templates import _as_page
			return _as_page(html, self.__attributes__)

		return html
