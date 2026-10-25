# Domino for client components: what a client component's module can import from `domino`
# (State and the tags), plus the runtime the browser's loader (domino/client.js) calls. It's
# plain Python that runs on MicroPython and Pyodide in the browser, and on CPython, where the
# server uses it to render client components' first HTML.

import json

from . import tags


class State:
	"""A value per component instance (`count = State(0)`); changing it renders the island again."""


	def __init__(self, value=None):

		self._value = value
		self._name = None


	def __set_name__(self, owner, name):

		self._name = name


	def __get__(self, instance, owner):

		if instance is None:
			return self

		key = "_domino_state_" + self._name
		try:
			return getattr(instance, key)
		except AttributeError:
			value = copy(self._value)
			setattr(instance, key, value)
			return value


	def __set__(self, instance, value):

		key = "_domino_state_" + self._name
		try:
			old = getattr(instance, key)
		except AttributeError:
			old = self._value
		setattr(instance, key, value)
		# Lists, dicts and sets may have been changed in place, so always count as changed
		if value != old or isinstance(value, (list, dict, set)):
			_changed.append(instance)



def copy(value):

	if isinstance(value, list):
		return [copy(item) for item in value]
	if isinstance(value, dict):
		return {key: copy(item) for key, item in value.items()}

	return value


class Event:
	"""What the browser sent with an event: `type`, the element's `value` (True/False for
	checkboxes), its form's fields (`form`), its data-* attributes (`data`), the pointer's position
	in the element (`x`, `y`) and the `key` pressed."""


	def __init__(self, type, value=None, form=None, data=None, x=None, y=None, key=None):

		self.type = type
		self.value = value
		self.form = form or {}
		self.data = data or {}
		self.x = x
		self.y = y
		self.key = key


	def __repr__(self):

		return "Event(type=%r, value=%r)" % (self.type, self.value)


# States changed since the island last rendered, and events for the server
_changed = []
_emits = []


def _emit(element, name, value):

	_emits.append([str(name), value])


# Loaded client modules ("<name>@<hash>" -> namespace) and mounted islands (element id -> Island)
modules = {}
islands = {}


def load_module(key, source, builtins=None, filename=None):
	"""Run a client component's module (once), known as "<module name>@<hash of its source>".
	`builtins` and `filename` are for the server, where `domino` is the server's own package:
	they map the module's imports of domino to this one, and name its file in tracebacks."""

	if key in modules:
		return modules[key]

	name = key.split("@")[0]
	namespace = {"__name__": name}
	if builtins is not None:
		namespace["__builtins__"] = builtins
	exec(compile(source, filename or name.replace(".", "/") + ".py", "exec"), namespace)
	modules[key] = namespace

	return namespace


class Island:
	"""A client component on the page and what its last render bound."""


	def __init__(self, island_id, component):

		self.id = island_id
		self.component = component
		self.handlers = []
		self.timers = []
		self.events = []
		self.html = None  # the last render's, for the browser to fetch with html()


	def render(self):

		frame = [self.id, 0, [], [], {}]
		tags._frame = frame
		try:
			self.component.__children__ = []
			html = self.component._render()
		finally:
			tags._frame = None
		self.handlers = frame[2]
		self.timers = frame[3]
		self.events = list(frame[4])
		del _changed[:]

		return html


def create(island_id, module, name, data):
	"""A new instance of a client component, with the State values and attributes the server
	rendered it with."""

	cls = modules[module][name]
	component = cls()
	for key, value in (data.get("state") or {}).items():
		setattr(component, key, value)
	component.configure(**(data.get("attrs") or {}))
	component.id(island_id)
	component.__attributes__["data_domino_client"] = "%s:%s" % (module, name)
	del _changed[:]

	return Island(island_id, component)


def render(island_id, module, name, data):
	"""The first HTML of a client component, rendered on the server (not mounted)."""

	island = create(island_id, module, name, data)
	island.component.__attributes__["data_domino_state"] = json.dumps(data, separators=(",", ":"))

	return island.render()


def mount(island_id, module, name, data_json):
	"""Take over the island the server rendered: returns its HTML as JSON with what to listen to."""

	try:
		island = create(island_id, module, name, json.loads(data_json))
		# For styles and tests: the browser runs it now
		island.component.__attributes__["data_domino_hydrated"] = True
		islands[island_id] = island
		return _result(island, island.render())
	except Exception as error:
		return _error(error)


def dispatch(island_id, kind, index, event_json):
	"""Run one of the island's handlers ("event") or timers ("after"), and render it again if
	its state changed."""

	island = islands.get(island_id)
	if island is None:
		return json.dumps({"error": "Unknown island %s" % island_id})

	del _changed[:]
	del _emits[:]
	try:
		if kind == "after":
			# A timer of an earlier render that this one no longer schedules
			if index >= len(island.timers):
				return _result(island, None)
			_call(island.timers[index][1], None)
		else:
			data = json.loads(event_json)
			_call(island.handlers[index], Event(
				data.get("type"), data.get("value"), data.get("form"), data.get("data"),
				data.get("x"), data.get("y"), data.get("key"),
			))
		html = island.render() if _changed else None
		return _result(island, html)
	except Exception as error:
		return _error(error)


def unmount(island_id):

	islands.pop(island_id, None)


def _call(callback, event):

	if event is None:
		callback()
		return

	takes = _takes_event(callback)
	if takes is not None:
		if takes:
			callback(event)
		else:
			callback()
		return

	# MicroPython can't tell how many arguments a function takes: try with the event first
	try:
		callback(event)
	except TypeError as error:
		if "positional argument" not in str(error):
			raise
		callback()


def _takes_event(callback):
	"""Whether `callback` takes the event, or None when this Python can't tell."""

	# MicroPython's inspect.signature() isn't CPython's
	import sys
	if sys.implementation.name != "cpython":
		return None

	try:
		import inspect
		parameters = inspect.signature(callback).parameters.values()
		return any(parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD, parameter.VAR_POSITIONAL) for parameter in parameters)
	except Exception:
		return None


def _result(island, html):
	"""What changed, as JSON. The HTML itself is fetched with html(): big strings are slow to
	put through JSON on MicroPython."""

	island.html = html

	return json.dumps({
		"html": html is not None,
		"events": island.events if html is not None else [],
		# Timers start when a render schedules them
		"after": [[index, delay] for index, (delay, _) in enumerate(island.timers)] if html is not None else [],
		"emit": list(_emits),
	})


def html(island_id):
	"""The HTML of the island's last render (see _result)."""

	island = islands.get(island_id)

	return island.html if island is not None else None


def _error(error):

	try:
		import traceback
		text = "".join(traceback.format_exception(type(error), error, error.__traceback__))
	except Exception:
		try:
			import io
			import sys
			buffer = io.StringIO()
			sys.print_exception(error, buffer)
			text = buffer.getvalue()
		except Exception:
			text = repr(error)

	return json.dumps({"error": "%s: %s" % (type(error).__name__, error), "traceback": text})
