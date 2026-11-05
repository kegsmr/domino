# Domino's tags for client components: the same classes as domino.tags on the server, rendering
# HTML in the browser. Runs on MicroPython (no __mro__, no inspect, read-only instance __dict__,
# unordered dicts) as well as CPython, which renders the first HTML of client components (SSR).


VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
RAW_TEXT_TAGS = {"script", "style"}

# Class attributes that are Domino settings, not HTML attributes (as in domino.util)
SETTINGS = {"attrs", "css", "client", "live", "optimistic", "optimistic_states", "tag", "submit_text"}



# `object` is also a tag below
_object = object

# What the render running now collects: [island id, ids made so far, handlers, timers, event types]
_frame = None

# Class -> (CSS class names, attributes from class attributes, has init(), has render()), worked out
# once per class: most elements are plain tags, and walking their classes each time is slow on
# MicroPython. And keyword -> HTML attribute name (None for private ones)
_class_info = {}
_names = {}


def escape(value):
	"""Like markupsafe.escape, which the server uses."""

	value = str(value)
	for character in "&<>\"'":
		if character in value:
			return (
				value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
				.replace('"', "&#34;").replace("'", "&#39;")
			)

	return value


def bases(cls):
	"""cls and its base classes, nearest first (MicroPython has no __mro__)."""

	found = []
	pending = [cls]
	while pending:
		current = pending.pop(0)
		if current in found or current is _object:
			continue
		found.append(current)
		pending.extend(current.__bases__)

	return found


def is_framework(cls):

	return cls is Element or "_domino_tag" in cls.__dict__


def class_info(cls, tag):

	found = bases(cls)
	names = []
	attributes = []
	methods = set()
	for base in found:
		if is_framework(base):
			continue
		methods.update(key for key in base.__dict__ if key in ("init", "render"))
		if base.__name__ == tag:
			continue
		name = base.__name__.replace("_", "-")
		if name not in names:
			names.append(name)
	# HTML attributes: the classes' `attrs`; other class attributes are Python (settings, props)
	merged = {}
	for base in reversed(found):
		if not is_framework(base) and "attrs" in base.__dict__:
			merged.update(base.__dict__["attrs"] or {})
	attributes = list(merged.items())
	info = _class_info[cls] = (names, attributes, "init" in methods, "render" in methods)

	return info


def flatten(children):
	"""Lists, tuples and generators flattened, None, True and False skipped, numbers made text
	(as on the server)."""

	flat = []
	for child in children:
		if isinstance(child, (str, Element)):
			flat.append(child)
		elif child is None or child is True or child is False:
			continue
		elif isinstance(child, (int, float)):
			flat.append(str(child))
		elif isinstance(child, (list, tuple)) or (hasattr(child, "__next__") and not isinstance(child, type)):
			flat.extend(flatten(child))
		else:
			flat.append(child)

	return flat


def attribute_name(key):

	name = _names.get(key, 0)
	if name == 0:
		if key.startswith("_"):
			name = None
		else:
			name = (key[:-1] if key.endswith("_") else key).replace("_", "-")
			# As on the server: names aren't escaped, so one from data mustn't end the tag
			if not name or any(character in " \t\n\r\f\"'<>/=" or ord(character) < 32 or ord(character) == 127 for character in name):
				raise ValueError("Invalid attribute name: %r" % (name,))
		_names[key] = name

	return name


def raw_text(tag, value):
	"""Text for a <script> or <style>, which only "</script" ("</style") could end early."""

	value = str(value)
	end = "</" + tag
	lower = value.lower()
	if end not in lower:
		return value

	out = []
	start = 0
	found = lower.find(end)
	while found != -1:
		out.append(value[start:found] + "<\\/")
		start = found + 2
		found = lower.find(end, start)
	out.append(value[start:])

	return "".join(out)


class Element:


	def __init__(self, tag=None, parent=None, inner=None, void=None, **kwargs):

		self.__children__ = []
		self.__tag__ = tag or ""
		self.__inner__ = inner
		self.__void__ = void
		self.__attributes__ = {}
		self.__id__ = None
		self.__id_used__ = False
		self.content_root = self

		if parent is not None:
			parent.__children__.append(self)

		if kwargs:
			self._configure(kwargs)

		info = _class_info.get(type(self)) or class_info(type(self), self.__tag__)
		if info[2]:
			self.init()


	def add_children(self, children):

		self.content_root.__children__.extend(flatten(children))
		return self


	def set_children(self, children):

		self.content_root.__children__ = flatten(children)
		return self


	def __getitem__(self, children):

		if isinstance(children, tuple):
			children = list(children)
		else:
			children = [children]
		return self.set_children(children)


	def __call__(self, children):

		return self.set_children(children)


	def __len__(self):

		return len(self.content_root.__children__)


	def __str__(self):

		return self._render()


	def tag(self, tag=None):

		if tag is None:
			return self.__tag__
		self.__tag__ = tag
		return self


	def inner(self, inner=None):

		if inner is None:
			return self.__inner__
		self.__inner__ = inner
		return self


	def id(self, id_=None):

		if id_ is not None:
			self.__attributes__["id"] = id_
			return self

		self.__id_used__ = True
		if self.__attributes__.get("id"):
			return str(self.__attributes__["id"])
		if self.__id__ is None:
			# The same in every render of the island, so the page keeps its nodes
			if _frame is not None:
				_frame[1] += 1
				self.__id__ = "%s-%d" % (_frame[0], _frame[1])
			else:
				self.__id__ = "domino-%d" % id(self)
		return str(self.__id__)


	def configure(self, **kwargs):

		return self._configure(kwargs)


	def _configure(self, kwargs):

		# on_click=handler binds the event like bind("click", handler)
		attributes = self.__attributes__
		bound = False
		for key in kwargs:
			value = kwargs[key]
			# on_click=(self.remove, index) calls self.remove(index) (see _call in domino/__init__.py)
			if key[:3] == "on_" and (callable(value) or (isinstance(value, tuple) and value and callable(value[0]))):
				self.bind(key[3:], value)
				bound = True
			else:
				attributes[key] = value
		if bound:
			attributes.pop("debounce", None)

		return self


	def bind(self, event, callback, debounce=None):
		"""Run `callback` in the browser when `event` happens on this element."""

		frame = _frame
		if frame is None:
			raise RuntimeError("Client components bind events in render()")

		event = event.lower()
		handlers = frame[2]
		item = event + ":" + str(len(handlers))
		handlers.append(callback)
		frame[4][event] = True
		bound = self.__attributes__.get("data_domino_on")
		self.__attributes__["data_domino_on"] = bound + " " + item if bound else item

		return self


	def after(self, delay, func):
		"""Call `func` in `delay` ms (once; render again to schedule the next time)."""

		if _frame is None:
			raise RuntimeError("Client components schedule after() in render()")

		timers = _frame[3]
		timers.append((int(delay), func))

		return self


	def emit(self, name, value=None):
		"""Send an event to the server: runs the handler the server component gave this
		component as on_<name>=..., with `value` as event.value (JSON values only)."""

		from . import _emit
		_emit(self, name, value)

		return self


	def _render(self):
		"""This element as HTML, without whitespace between tags."""

		out = []
		write(self, out)

		return "".join(out)


def write(element, out):
	"""Append `element`'s HTML to the list `out`."""

	cls = type(element)
	info = _class_info.get(cls) or class_info(cls, element.__tag__)
	names, class_attributes, _, renders = info

	if renders:
		children = element.render()
		if children is not None and children is not element:
			if not isinstance(children, (list, tuple)):
				children = [children]
			element.set_children(list(children))

	tag = element.__tag__
	attributes = element.__attributes__

	extra = attributes.get("class")
	more = attributes.get("class_")
	if extra or more:
		names = list(names)
		for value in (extra, more):
			if isinstance(value, str):
				value = value.split()
			for name in value or ():
				if name not in names:
					names.append(name)

	out.append("<" + tag)
	if names:
		out.append(' class="' + escape(" ".join(names)) + '"')

	if element.__id_used__ or info[0]:
		out.append(' id="' + escape(element.id()) + '"')
		skip_id = True
	else:
		skip_id = False

	for key, value in class_attributes:
		if key not in attributes:
			write_attribute(out, key, value)

	for key in attributes:
		if key == "class" or key == "class_" or (skip_id and key == "id"):
			continue
		write_attribute(out, key, attributes[key])

	out.append(">")

	void = element.__void__
	if void or (void is None and tag in VOID_TAGS):
		return

	raw = tag in RAW_TEXT_TAGS
	inner = element.__inner__
	if inner:
		out.append(raw_text(tag, inner) if raw else escape(inner))

	for child in element.__children__:
		if isinstance(child, str):
			out.append(raw_text(tag, child) if raw else escape(child))
			continue
		if not isinstance(child, Element) and callable(child):
			child = child()
		if isinstance(child, type):
			child = child()
		if isinstance(child, Element):
			write(child, out)
		elif isinstance(child, str):
			out.append(raw_text(tag, child) if raw else escape(child))
		else:
			raise ValueError("Invalid child: %r" % (child,))

	out.append("</" + tag + ">")


def write_attribute(out, key, value):

	if value is None or value is False:
		return
	name = attribute_name(key)
	if name is None:
		return
	if value is True:
		out.append(" " + name)
		return
	if name == "style" and isinstance(value, dict):
		value = "; ".join("%s: %s" % (property.replace("_", "-"), css) for property, css in value.items())
	out.append(" " + name + '="' + escape(value) + '"')


class _Tag(Element):

	_domino_tag = True


	def __init__(self, parent=None, inner=None, *args, **kwargs):

		Element.__init__(self, self._tag_name, parent, inner, *args, **kwargs)


TAGS = (
	"html", "head", "body", "title", "meta", "link", "style", "base",
	"noscript", "script", "section", "article", "aside", "nav", "header",
	"footer", "main", "h1", "h2", "h3", "h4", "h5", "h6", "p", "hr",
	"pre", "blockquote", "ol", "ul", "li", "dl", "dt", "dd", "figure",
	"figcaption", "div", "a", "em", "strong", "small", "s", "cite",
	"q", "abbr", "code", "sub", "sup", "time", "mark", "b", "i", "u",
	"span", "br", "wbr", "img", "iframe", "embed", "object", "param",
	"video", "audio", "source", "track", "map", "area", "canvas", "svg",
	"table", "tr", "td", "th", "thead", "tbody", "tfoot", "col", "colgroup",
	"form", "input", "textarea", "button",
	"label", "select", "option", "optgroup", "fieldset", "legend",
	"datalist", "output", "progress", "meter", "details", "summary",
	"dialog", "caption",
)


for _name in TAGS:
	globals()[_name] = type(_name, (_Tag,), {"_tag_name": _name, "_domino_tag": True})

del _name
