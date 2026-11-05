"""Turns nested style blocks, or CSS text, into CSS.

A block is a dict of declarations and nested rules, relative to a selector:

	{
		"padding": "1rem",                  # padding: 1rem (underscores become hyphens)
		"__accent": "teal",                 # --accent: teal (a CSS variable)
		"h3": {"margin": 0},                # <selector> h3
		":hover": {...},                    # <selector>:hover (also "::after", "[open]")
		"& + &": {...},                     # & stands for the selector
		"@media (max-width: 600px)": {...}, # the same kind of block, inside the media query
		"@keyframes spin": {"to": {...}},   # other at-rules are written as they are, unscoped
	}
"""

import re


# At-rules that contain style rules, so the enclosing selector carries into them
GROUP_RULES = ("@media", "@supports", "@container", "@layer", "@scope", "@starting-style")


def render(styles, selector=""):
	"""CSS for a block, e.g. Style.styles ({selector: block}) or a component's css under its selector."""

	if isinstance(styles, str):
		styles = parse(styles)

	lines = []
	rule(lines, selector, styles, "")

	return escape("\n".join(lines))


def rule(lines, selector, block, indent):

	# Without a selector, declarations go directly inside an at-rule (such as @font-face)
	prefix = indent
	if selector:
		prefix = indent + "\t"

	declarations = []
	nested = []
	for key, value in items(block):
		if isinstance(value, (dict, list)):
			nested.append((key.strip(), value))
		elif value is not None and value is not False:
			declarations.append(f"{prefix}{property_name(key)}: {value};")

	if declarations and selector:
		lines.append(f"{indent}{selector} {{")
		lines.extend(declarations)
		lines.append(f"{indent}}}")
	elif declarations:
		lines.extend(declarations)

	for key, value in nested:
		if not key.startswith("@"):
			rule(lines, nest(selector, key), value, indent)
			continue
		lines.append(f"{indent}{key} {{")
		if re.match(r"@[\w-]+", key).group() in GROUP_RULES:
			rule(lines, selector, value, indent + "\t")
		else:
			rule(lines, "", value, indent + "\t")
		lines.append(f"{indent}}}")


def items(block):

	if isinstance(block, dict):
		return block.items()

	return block


def property_name(name):

	# Custom properties are case- and underscore-sensitive, so keep them as written
	if name.startswith("--"):
		return name

	return name.replace("_", "-")


def variable_name(name):
	"""primary, __primary or --primary -> --primary"""

	if name.startswith("--"):
		return name

	return "--" + name.lstrip("_").replace("_", "-")


def nest(parent, key):
	"""The selector for `key` nested in `parent`: descendants by default, while
	pseudo-classes, pseudo-elements and attribute selectors attach to the parent."""

	# The original shorthand, from Style.style(..., hover={...})
	if key == "hover":
		key = ":hover"

	if not parent:
		return key

	selectors = []
	for outer in split(parent):
		for inner in split(key):
			if "&" in inner:
				selectors.append(inner.replace("&", outer))
			elif not inner:
				selectors.append(outer)
			elif inner[0] in ":[":
				selectors.append(outer + inner)
			else:
				selectors.append(f"{outer} {inner}")

	return ", ".join(selectors)


def split(selector):
	"""A selector list split on its top-level commas (not those inside :is(...) or [...])."""

	# Most selectors are a single one; skip the scan (per-element styles render often)
	if "," not in selector:
		return [selector.strip()]

	parts = []
	depth = 0
	quote = None
	start = 0
	for index, char in enumerate(selector):
		if quote:
			if char == quote:
				quote = None
		elif char in "\"'":
			quote = char
		elif char in "([":
			depth += 1
		elif char in ")]":
			depth -= 1
		elif char == "," and depth == 0:
			parts.append(selector[start:index].strip())
			start = index + 1
	parts.append(selector[start:].strip())

	return parts


def parse(text):
	"""CSS text as a block of (key, value) pairs; rules inside rules are nested, as in the dicts."""

	text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)

	return parse_block(text, 0)[0]


def parse_block(text, index):

	# Pairs rather than a dict, so repeated properties (fallbacks) are all kept
	block = []
	start = index
	depth = 0
	quote = None
	while index < len(text):
		char = text[index]
		if quote:
			if char == "\\":
				index += 1
			elif char == quote:
				quote = None
		elif char in "\"'":
			quote = char
		elif char == "(":
			depth += 1
		elif char == ")":
			depth -= 1
		elif depth == 0 and char == ";":
			add_declaration(block, text[start:index])
			start = index + 1
		elif depth == 0 and char == "{":
			prelude = text[start:index].strip()
			body, index = parse_block(text, index + 1)
			block.append((prelude, body))
			start = index + 1
		elif depth == 0 and char == "}":
			add_declaration(block, text[start:index])
			return block, index
		index += 1

	add_declaration(block, text[start:])

	return block, index


def add_declaration(block, text):

	name, colon, value = text.partition(":")
	if colon and name.strip():
		block.append((name.strip(), value.strip()))


def merge(target, rules):
	"""Add `rules` to the block `target`, merging nested blocks instead of replacing them."""

	for key, value in rules.items():
		if isinstance(value, dict) and isinstance(target.get(key), dict):
			merge(target[key], value)
		else:
			target[key] = value

	return target


def escape(css):

	# Inside <style>, only "</style" ends the element; "<\/" means the same in CSS
	return css.replace("</", "<\\/")
