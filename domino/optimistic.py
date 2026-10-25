"""Optimistic updates: which handlers can be run ahead of time to predict a component's next look.

A handler qualifies when it only changes the component's own State, its local variables and
copies of plain values, using plain expressions (arithmetic, comparisons, f-strings, literals and
comprehensions, a few builtins and the methods of str, list, dict and set) of constants, those
attributes and its parameters, inside if/else and for loops. It may call other such methods of
the component, read `event.value` when the element can only send a few values (a <select>'s
options, a checkbox), read `event.form[...]` (see Placeholder), and read and write the app's
Collections (writes go to the prediction's overlay, see domino.reactive). So does a lambda that
only calls such a method of the component with plain values (`lambda event, index=index:
self.select(index)`), or a functools.partial of one. Anything else (calls of other functions,
other objects, globals) is never run ahead of time.

That's checked by reading the code (Checker), and enforced when a prediction runs: it runs a copy
of the method compiled with nothing but safe builtins in reach, whose method calls go through
call_method(), which checks the value's type, and only ever sees copies of plain values (State
values that aren't plain data stop it). Running it can then have no effect outside the prediction.

The server follows those handlers from the component's current state to every state they reach,
renders each state once, and ships them with which event leads where (see graph()). The browser
then shows the result of any number of clicks the moment they happen, while the events still go
to the server in order and its answers confirm or correct what's shown. When the states are too
many (a counter can go up forever, a list can grow), it ships just the states one event away.
"""

import ast
import builtins
import functools
import inspect
import itertools
import json
import linecache
import textwrap
import threading
import time
import types
from copy import deepcopy
from datetime import date, datetime, time as daytime, timedelta
from decimal import Decimal
from fractions import Fraction
from uuid import UUID

from markupsafe import Markup

from . import patches, reactive
from .reactive import DATA, Collection, Cursor, State
from .util import accepts_argument


# Plain functions allowed in a predictable handler: they have no side effects
SAFE_CALLS = {
	"len", "min", "max", "abs", "round", "str", "int", "float", "bool", "sorted", "sum", "list", "dict",
	"set", "tuple", "frozenset", "range", "enumerate", "zip", "reversed", "any", "all", "divmod",
}

# Methods a handler may call, per type of value: those that read it or change only the value
# itself (predictions only see copies). Checked when a prediction runs, by the value's exact type
STR_METHODS = {
	"lower", "upper", "strip", "lstrip", "rstrip", "startswith", "endswith", "split", "rsplit", "splitlines",
	"join", "replace", "title", "capitalize", "count", "find", "rfind", "index", "rindex", "isdigit", "isalpha",
	"isalnum", "isspace", "islower", "isupper", "isdecimal", "isnumeric", "partition", "rpartition",
	"removeprefix", "removesuffix", "swapcase",
}
SET_METHODS = {
	"union", "intersection", "difference", "symmetric_difference", "issubset", "issuperset", "isdisjoint", "copy",
}
METHODS = {
	str: STR_METHODS,
	list: {"index", "count", "copy", "append", "extend", "insert", "remove", "pop", "clear", "sort", "reverse"},
	dict: {"get", "keys", "values", "items", "copy", "update", "setdefault", "pop", "popitem", "clear"},
	set: SET_METHODS | {
		"add", "discard", "remove", "pop", "clear", "update", "difference_update", "intersection_update",
		"symmetric_difference_update",
	},
	frozenset: SET_METHODS,
	tuple: {"index", "count"},
	# Writes while predicting are kept aside (see domino.reactive), and reads see them
	Collection: {"insert", "update", "remove", "find", "find_one", "count"},
	Cursor: {"fetch", "count"},
}

# Functions of modules a handler may call (the module must be imported under its own name)
MODULE_CALLS = {time: {"time"}}

SAFE_EXPRESSIONS = (
	ast.Constant, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
	ast.JoinedStr, ast.FormattedValue, ast.Tuple, ast.List, ast.Set, ast.Slice,
	ast.operator, ast.unaryop, ast.boolop, ast.cmpop, ast.expr_context,
)

COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)

# Predictions cost a render each, so one step ahead shows at most this many states
MAX_PREDICTIONS = 24

# The whole graph is shipped only when the states it reaches are at most this many (counting the
# current one; a class sets its own with `optimistic_states = n`) and their HTML (as sent, large
# states being patches) at most this long
MAX_STATES = 16
MAX_BYTES = 32 * 1024

# An event whose element can send at most this many values (a <select>'s options) is predicted
# for each of them
MAX_CHOICES = 16

# A form submitted again before the server answered is predicted this many times in a row
CHAIN = 2

# A prediction stops beyond this many numbers in a range(), this many steps of its loops in all,
# or making a sequence this long with *
MAX_RANGE = 10000
MAX_STEPS = 100000
MAX_SIZE = 1000000

# Values a prediction can share with the real state instead of copying
ATOMIC = (int, float, complex, str, bytes, bool, type(None))

# Plain data: what State values must be for a prediction to run, so that its operators, hashing
# and iteration are the builtin, side-effect-free ones
PLAIN = ATOMIC + (Decimal, Fraction, date, datetime, daytime, timedelta, UUID, Markup)
CONTAINERS = (list, tuple, dict, set, frozenset)

try:
	from bson import ObjectId
	PLAIN += (ObjectId,)
except ImportError:  # pragma: no cover - pymongo comes with bson
	pass

_analyses = {}  # class -> (handlers: {name: uses}, callable: {name: (parameters, uses)})
_compiled = {}  # (class, method name) -> the method as predictions run it, or None
_lambdas = {}  # lambda code object -> LambdaCall, or None
_sources = {}  # file name -> {line: [ast.Lambda nodes starting there]}
_state_lists = {}  # class -> its State attribute names, sorted


class Unpredictable(Exception):
	"""Raised while predicting when a handler does what its prediction can't stand in for."""


def forget():
	"""Forget what was worked out per class or file (see domino.hot)."""

	for cache in (_analyses, _compiled, _lambdas, _sources, _state_lists):
		cache.clear()


def state_names(cls):
	"""Names of the State attributes of a component class (including inherited ones)."""

	names = set()
	for base in cls.__mro__:
		for name, value in vars(base).items():
			if isinstance(value, State):
				names.add(name)

	return names


def predictable_methods(cls):
	"""Names of the methods of `cls` that can be run ahead of time as handlers (computed once
	per class). Those that read event.value are predicted only for elements with a few values."""

	return set(analysis(cls)[0])


def callable_methods(cls):
	"""{name: number of parameters} of the methods of `cls` a predictable handler or lambda may
	call: like predictable methods, but their parameters (all required) may be read."""

	return {name: count for name, (count, _) in analysis(cls)[1].items()}


def analysis(cls):

	if cls not in _analyses:
		_analyses[cls] = analyze(cls)

	return _analyses[cls]


def analyze(cls):
	"""({name: what it uses} of the methods that qualify as handlers, {name: (number of
	parameters, what it uses)} of those that qualify as methods a handler calls)."""

	states = state_names(cls)
	found = {}
	for name, function in inspect.getmembers(cls, inspect.isfunction):
		if name.startswith("_") or name in ("render", "init") or function.__module__ in ("domino.core", "domino.components"):
			continue
		definition = parse_function(function)
		if definition is not None:
			found[name] = (function, definition)

	# Methods a handler may call do only what's allowed, calling only each other: assume all
	# of them qualify, then drop those that don't until none is dropped
	callable_ = {}
	for name, (function, definition) in found.items():
		arguments = definition.args
		if not arguments.defaults:
			callable_[name] = len(arguments.args) - 1
	checked = {}
	while True:
		checked = {}
		for name in callable_:
			function, definition = found[name]
			checker = method_checker(function, definition, states, callable_, read_parameters=True)
			if checker.function(definition):
				checked[name] = checker
		if len(checked) == len(callable_):
			break
		callable_ = {name: callable_[name] for name in checked}

	handlers = {}
	for name, (function, definition) in found.items():
		checker = method_checker(function, definition, states, callable_)
		if checker is not None and checker.function(definition):
			handlers[name] = checker

	# What a method uses includes what the methods it calls use
	def uses(checker, seen):
		used = set(checker.uses)
		for name in checker.calls - seen:
			seen.add(name)
			used |= uses(checked[name], seen)
		return used

	return (
		{name: frozenset(uses(checker, set())) for name, checker in handlers.items()},
		{name: (callable_[name], frozenset(uses(checker, {name}))) for name, checker in checked.items()},
	)


def method_checker(function, definition, states, methods, read_parameters=False):
	"""A Checker for a method: as a handler, it takes at most the event besides self; as a
	method a handler calls, its parameters may be read. None if it takes more than the event."""

	arguments = definition.args
	self_name = arguments.args[0].arg
	others = [argument.arg for argument in arguments.args[1:]]
	names = module_names(function.__globals__)
	if read_parameters:
		return Checker(self_name, states, params=others, methods=methods, names=names)
	if len(others) > 1:
		return None

	return Checker(self_name, states, event=others[0] if others else None, methods=methods, names=names)


def module_names(namespace):
	"""The names in a module's globals a handler may use: its Collections, and modules whose
	functions it may call."""

	return {
		name: value for name, value in list(namespace.items())
		if type(value) is Collection or (isinstance(value, types.ModuleType) and value in MODULE_CALLS)
	}


def parse_function(function):

	try:
		tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
	except (OSError, TypeError, SyntaxError):
		return None

	definition = tree.body[0]
	if not isinstance(definition, ast.FunctionDef) or definition.decorator_list:
		return None

	arguments = definition.args
	if arguments.vararg or arguments.kwarg or arguments.kwonlyargs or not arguments.args:
		return None
	if getattr(arguments, "posonlyargs", None):
		return None

	return definition


def assigned_names(statements):
	"""The names a function's statements assign, which are its local variables (never globals);
	comprehensions have their own."""

	names = set()
	stack = list(statements)
	while stack:
		node = stack.pop()
		if isinstance(node, COMPREHENSIONS + (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
			continue
		if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
			names.add(node.id)
		stack.extend(ast.iter_child_nodes(node))

	return names


class Checker:
	"""Whether code only does what a prediction may (see the module's docstring). Records what it
	uses besides the component's State ("value" and "form" of the event, "data" of collections),
	the methods of the component it calls, and the first reason it doesn't qualify, for explain()."""


	def __init__(self, self_name, states, event=None, params=(), methods=None, names=None):

		self.self_name = self_name
		self.states = states
		self.event = event  # the event parameter, of which only .value and .form[...] may be read
		self.params = set(params)  # names that may be read (a method's parameters)
		self.methods = methods or {}  # {name: number of parameters} of the methods it may call
		self.names = names or {}  # globals it may use (see module_names)
		self.locals = set()
		self.scopes = []  # names of the comprehensions it's in
		self.loops = 0
		self.uses = set()
		self.calls = set()
		self.reason = None
		self.node = None


	def fail(self, node, reason):

		if self.reason is None:
			self.reason = reason
			self.node = node

		return False


	def function(self, definition):

		self.locals = assigned_names(definition.body)

		return self.body(definition.body)


	def body(self, statements):

		return all(self.statement(statement) for statement in statements)


	def statement(self, node):

		if isinstance(node, ast.Pass):
			return True
		if isinstance(node, ast.Expr):
			# A docstring, or a call for what it does (self.items.append(x))
			return isinstance(node.value, ast.Constant) or self.expression(node.value)
		if isinstance(node, ast.Assign):
			return all(self.target(target) for target in node.targets) and self.expression(node.value)
		if isinstance(node, ast.AugAssign):
			return self.target(node.target) and self.expression(node.value)
		if isinstance(node, ast.Delete):
			return all(self.deletable(target) for target in node.targets)
		if isinstance(node, ast.If):
			return self.expression(node.test) and self.body(node.body) and self.body(node.orelse)
		if isinstance(node, ast.For):
			self.loops += 1
			loop = self.target(node.target) and self.expression(node.iter) and self.body(node.body)
			self.loops -= 1
			return loop and self.body(node.orelse)
		if isinstance(node, (ast.Break, ast.Continue)):
			return self.loops > 0 or self.fail(node, "break and continue only belong in a loop")
		if isinstance(node, ast.Return):
			if node.value is None or (isinstance(node.value, ast.Constant) and node.value.value is None):
				return True
			return self.fail(node, "it returns a value (the component it re-renders is up to the server)")
		if isinstance(node, ast.While):
			return self.fail(node, "while loops aren't followed, since they might not end (a for loop over a list or range() is)")
		if isinstance(node, (ast.With, ast.Try, ast.Raise, ast.Assert)):
			return self.fail(node, "only assignments, calls of allowed methods, if/else, for loops and return are followed, not with, try, raise or assert")
		if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
			return self.fail(node, "it imports or declares globals, which could change things outside the component")
		if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
			return self.fail(node, "it defines a function or class")

		return self.fail(node, "only assignments, calls of allowed methods, if/else, for loops and return are followed")


	def state_attribute(self, node):

		return (
			self.self_name is not None
			and isinstance(node, ast.Attribute)
			and isinstance(node.value, ast.Name)
			and node.value.id == self.self_name
			and node.attr in self.states
		)


	def target(self, node):

		if self.state_attribute(node):
			return True
		if isinstance(node, ast.Name):
			if node.id in (self.self_name, self.event):
				return self.fail(node, f"it assigns to {node.id}")
			return True  # a local variable (see assigned_names)
		if isinstance(node, (ast.Tuple, ast.List)):
			return all(self.target(element) for element in node.elts)
		if isinstance(node, ast.Starred):
			return self.target(node.value)
		if isinstance(node, ast.Subscript):
			# Changes a copy (self.flags[key] = value)
			return self.expression(node.value) and self.expression(node.slice)

		return self.fail(node, "it changes something other than the component's own State or a local variable")


	def deletable(self, node):

		if isinstance(node, ast.Subscript):
			return self.expression(node.value) and self.expression(node.slice)
		if isinstance(node, ast.Name) and node.id in self.locals:
			return True

		return self.fail(node, "it deletes something other than an item of a list or dict, or a local variable")


	def readable(self, name):

		if name in (self.self_name, self.event):
			return False

		return name in self.params or name in self.locals or any(name in scope for scope in self.scopes)


	def event_value(self, node):

		if (
			self.event is not None and isinstance(node, ast.Attribute) and node.attr == "value"
			and isinstance(node.value, ast.Name) and node.value.id == self.event
		):
			self.uses.add("value")
			return True

		return False


	def event_form(self, node):

		return (
			self.event is not None and isinstance(node, ast.Attribute) and node.attr == "form"
			and isinstance(node.value, ast.Name) and node.value.id == self.event
		)


	def form_field(self, node):

		if self.event_form(node.value) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
			self.uses.add("form")
			return True

		return False


	def expression(self, node):

		if self.state_attribute(node):
			return True
		if isinstance(node, ast.Name):
			if isinstance(node.ctx, ast.Load) and self.readable(node.id):
				return True
			if node.id == self.event:
				return self.fail(node, "it reads the event, which isn't known before the click (only event.value of an element with a few values, and event.form[...] are)")
			return self.fail(node, f"it reads {node.id}, which isn't the component's State, a local variable or a parameter")
		if isinstance(node, ast.Attribute):
			if self.event_value(node):
				return True
			if self.event_form(node):
				return self.fail(node, "it reads event.form other than by a field's name (event.form[\"name\"] or event.form.get(\"name\"))")
			return self.fail(node, "it reads an attribute of something other than the component's State")
		if isinstance(node, ast.Subscript):
			if self.form_field(node):
				return True
			return self.expression(node.value) and self.expression(node.slice)
		if isinstance(node, ast.Call):
			return self.call(node)
		if isinstance(node, COMPREHENSIONS):
			return self.comprehension(node)
		if isinstance(node, ast.Dict):
			if any(key is None for key in node.keys):
				return self.fail(node, "it unpacks a dict with **")
			return all(self.expression(key) for key in node.keys) and all(self.expression(value) for value in node.values)
		if isinstance(node, ast.Starred):
			return self.expression(node.value)
		if not isinstance(node, SAFE_EXPRESSIONS):
			return self.fail(node, f"it uses {type(node).__name__}, which isn't one of the plain expressions followed")

		return all(self.expression(child) for child in ast.iter_child_nodes(node))


	def comprehension(self, node):

		names = set()
		self.scopes.append(names)
		try:
			for generator in node.generators:
				if generator.is_async:
					return self.fail(node, "it uses an async comprehension")
				# The first iterable is read outside the comprehension: before its variables
				if not self.expression(generator.iter) or not self.comprehension_target(generator.target, names):
					return False
				if not all(self.expression(test) for test in generator.ifs):
					return False
			if isinstance(node, ast.DictComp):
				return self.expression(node.key) and self.expression(node.value)
			return self.expression(node.elt)
		finally:
			self.scopes.pop()


	def comprehension_target(self, node, names):

		if isinstance(node, ast.Name) and node.id not in (self.self_name, self.event):
			names.add(node.id)
			return True
		if isinstance(node, (ast.Tuple, ast.List)):
			return all(self.comprehension_target(element, names) for element in node.elts)

		return self.fail(node, "a comprehension's variables must be plain names")


	def call(self, node):

		for keyword in node.keywords:
			if keyword.arg is None:
				return self.fail(node, "it passes arguments with **")
		arguments = list(node.args) + [keyword.value for keyword in node.keywords]
		function = node.func

		if isinstance(function, ast.Name):
			if function.id not in SAFE_CALLS or self.readable(function.id):
				return self.fail(node, f"it calls {function.id}(), which could change things outside the component")
		elif not isinstance(function, ast.Attribute):
			return self.fail(node, "it calls something other than a function by its name or a method")
		elif self.self_name is not None and isinstance(function.value, ast.Name) and function.value.id == self.self_name:
			# Another method of the component, with as many plain values as it takes
			count = self.methods.get(function.attr)
			if count is None:
				return self.fail(node, f"it calls self.{function.attr}(), which isn't a predictable method of the component")
			if node.keywords or len(node.args) != count or any(isinstance(argument, ast.Starred) for argument in node.args):
				return self.fail(node, f"it calls self.{function.attr}() with other than its {count} parameter(s), by position")
			self.calls.add(function.attr)
		elif self.event_form(function.value):
			if function.attr != "get" or node.keywords or not 1 <= len(node.args) <= 2 or not (
				isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
			):
				return self.fail(node, "it reads event.form other than by a field's name (event.form[\"name\"] or event.form.get(\"name\"))")
			self.uses.add("form")
			arguments = node.args[1:]
		elif isinstance(function.value, ast.Name) and function.value.id in self.names and not self.readable(function.value.id):
			value = self.names[function.value.id]
			if type(value) is Collection and function.attr in METHODS[Collection]:
				self.uses.add("data")
			elif function.attr not in MODULE_CALLS.get(value, ()):
				return self.fail(node, f"it calls {function.value.id}.{function.attr}(), which could change things outside the component")
		elif any(function.attr in methods for methods in METHODS.values()):
			if not self.expression(function.value):
				return False
		else:
			return self.fail(node, f"it calls .{function.attr}(), which isn't a method of plain values known to be safe")

		return all(self.expression(argument) for argument in arguments)


# Running predictions -----------------------------------------------------------------------------


OPEN, CLOSE = "", ""


class Placeholder(str):
	"""What a predicted handler reads for a form field, which only the browser knows: a marker
	(private-use characters around a number) that core.js replaces, wherever the predicted HTML
	has it, with what was typed, escaped. So the value may only go into the HTML as it is, or
	changed in ways core.js does the same way: strip(), lower(), upper(), [:n] (each recorded in
	the marker). Anything else, like comparing or replacing parts of it, stops the prediction or
	turns out wrong (the server then puts it right). It counts as non-empty: core.js predicts only
	when the field isn't blank."""


	def __new__(cls, slot, transforms=""):

		value = str.__new__(cls, f"{OPEN}{slot}{transforms}{CLOSE}")
		value.slot = slot
		value.transforms = transforms

		return value


	def __getnewargs__(self):

		return (self.slot, self.transforms)


	def __copy__(self):

		return self


	def __deepcopy__(self, memo):

		return self


	def then(self, transform):

		return Placeholder(self.slot, self.transforms + transform)


	def strip(self, chars=None):

		if chars is not None:
			raise Unpredictable("strip() of a form field with characters")
		return self.then("s")


	def lstrip(self, chars=None):

		if chars is not None:
			raise Unpredictable("lstrip() of a form field with characters")
		return self.then("<")


	def rstrip(self, chars=None):

		if chars is not None:
			raise Unpredictable("rstrip() of a form field with characters")
		return self.then(">")


	def lower(self):

		return self.then("l")


	def upper(self):

		return self.then("u")


	def __getitem__(self, key):

		if (
			isinstance(key, slice) and key.start in (None, 0) and key.step in (None, 1)
			and isinstance(key.stop, int) and key.stop >= 0
		):
			return self.then(f"t{key.stop};")
		raise Unpredictable("a form field indexed other than by [:n]")


	def __len__(self):

		return 1


	def __format__(self, spec):

		if spec:
			raise Unpredictable("a form field formatted with a format spec")
		return str.__str__(self)


def _refuse(name):

	def refuse(self, *args, **kwargs):
		raise Unpredictable(f"{name}() of a form field, which only the browser knows")

	refuse.__name__ = name
	return refuse


for _name in [name for name in dir(str) if not name.startswith("_")] + ["__contains__", "__iter__", "__mod__", "__rmod__", "__mul__", "__rmul__"]:
	if _name not in vars(Placeholder):
		setattr(Placeholder, _name, _refuse(_name))


METHODS[Placeholder] = {"strip", "lstrip", "rstrip", "lower", "upper"}


class PredictedForm:
	"""event.form while predicting: each field read is a Placeholder with a number of its own."""


	def __init__(self, slots):

		self.slots = slots  # where the numbers come from, or None when there's no form to stand for
		self.fields = {}  # name -> number


	def __getitem__(self, name):

		if self.slots is None or not isinstance(name, str):
			raise Unpredictable("event.form")
		if name not in self.fields:
			self.fields[name] = next(self.slots)

		return Placeholder(self.fields[name])


	def get(self, name, default=None):

		return self[name]


METHODS[PredictedForm] = {"get"}


class PredictedEvent:
	"""The event while predicting: the value it's predicted for, and its form's fields."""


	def __init__(self, value=None, slots=None):

		self.value = value
		self.form = PredictedForm(slots)


def safe_range(*arguments):

	numbers = range(*arguments)
	if len(numbers) > MAX_RANGE:
		raise Unpredictable("range() of more than MAX_RANGE numbers")

	return numbers


_steps = threading.local()


def counted(iterable):
	"""The items of a for loop's or comprehension's iterable in a prediction, at most MAX_STEPS in
	all per prediction, so a prediction always ends quickly."""

	for item in iterable:
		_steps.left = getattr(_steps, "left", MAX_STEPS) - 1
		if _steps.left < 0:
			raise Unpredictable("more than MAX_STEPS loop steps")
		yield item


def checked_operation(left, right, operator):
	"""left * right, left ** right or left << right in a prediction, unless the result would be
	huge (a string repeated a billion times)."""

	if operator == "*":
		for sequence, count in ((left, right), (right, left)):
			if isinstance(sequence, (str, bytes, list, tuple)) and isinstance(count, int) and len(sequence) * count > MAX_SIZE:
				raise Unpredictable("a sequence repeated too many times")
		return left * right
	if operator == "**":
		if isinstance(left, int) and isinstance(right, int) and abs(left) > 1 and right > 1000:
			raise Unpredictable("a power too large")
		return left ** right
	if isinstance(right, int) and right > 10000:
		raise Unpredictable("a shift too large")

	return left << right


def call_method(receiver, name, /, *arguments, **keywords):
	"""receiver.name(...) in a prediction, if that's a method allowed for the receiver's type."""

	allowed = MODULE_CALLS.get(receiver) if isinstance(receiver, types.ModuleType) else METHODS.get(type(receiver))
	if not allowed or name not in allowed:
		raise Unpredictable(f"{type(receiver).__name__}.{name}()")

	return getattr(receiver, name)(*arguments, **keywords)


def call_own(component, name, /, *arguments):
	"""self.name(...) in a prediction: the method as predictions run it."""

	if name not in analysis(type(component))[1]:
		raise Unpredictable(f"self.{name}()")

	return compiled(type(component), name)(component, *arguments)


SANDBOX = {name: getattr(builtins, name) for name in SAFE_CALLS}
SANDBOX.update({
	"range": safe_range, "__builtins__": {}, "__domino_method__": call_method, "__domino_own__": call_own,
	"__domino_counted__": counted, "__domino_operation__": checked_operation,
})

GUARDED_OPERATORS = {ast.Mult: "*", ast.Pow: "**", ast.LShift: "<<"}


class Instrument(ast.NodeTransformer):
	"""Turns checked code into what predictions run: method calls go through call_method() (or
	call_own() for the component's own methods), which check what's called when it runs; loops
	count their steps (counted()), and *, ** and << check the result's size."""


	def __init__(self, self_name):

		self.self_name = self_name


	@staticmethod
	def helper(name, arguments, node):

		return ast.copy_location(ast.Call(func=ast.Name(id=name, ctx=ast.Load()), args=arguments, keywords=[]), node)


	def visit_For(self, node):

		self.generic_visit(node)
		node.iter = self.helper("__domino_counted__", [node.iter], node.iter)

		return node


	def visit_comprehension(self, node):

		self.generic_visit(node)
		node.iter = self.helper("__domino_counted__", [node.iter], node.iter)

		return node


	def visit_BinOp(self, node):

		self.generic_visit(node)
		operator = GUARDED_OPERATORS.get(type(node.op))
		if operator is None:
			return node

		return self.helper("__domino_operation__", [node.left, node.right, ast.Constant(value=operator)], node)


	def visit_AugAssign(self, node):

		self.generic_visit(node)
		operator = GUARDED_OPERATORS.get(type(node.op))
		if operator is None:
			return node

		# target = operation(target, value): the target is a name, an attribute or an item,
		# reading which has no effect
		read = deepcopy(node.target)
		for child in ast.walk(read):
			if hasattr(child, "ctx"):
				child.ctx = ast.Load()
		value = self.helper("__domino_operation__", [read, node.value, ast.Constant(value=operator)], node)

		return ast.copy_location(ast.Assign(targets=[node.target], value=value), node)


	def visit_Call(self, node):

		self.generic_visit(node)
		function = node.func
		if not isinstance(function, ast.Attribute):
			return node

		own = self.self_name is not None and isinstance(function.value, ast.Name) and function.value.id == self.self_name
		helper = ast.Name(id="__domino_own__" if own else "__domino_method__", ctx=ast.Load())
		call = ast.Call(func=helper, args=[function.value, ast.Constant(value=function.attr)] + node.args, keywords=node.keywords)

		return ast.copy_location(call, node)


def compiled(cls, name):
	"""The method `name` of `cls` as predictions run it (see Instrument), with only safe builtins,
	and the Collections and modules it uses, in reach. Compiled once."""

	key = (cls, name)
	if key not in _compiled:
		_compiled[key] = None
		function = getattr(cls, name, None)
		definition = parse_function(function) if isinstance(function, types.FunctionType) else None
		if definition is not None:
			# Defaults and annotations are evaluated where it's defined: leave them out
			arguments = definition.args
			arguments.defaults = []
			definition.returns = None
			for argument in arguments.args:
				argument.annotation = None
			definition = Instrument(arguments.args[0].arg).visit(definition)
			module = ast.fix_missing_locations(ast.Module(body=[definition], type_ignores=[]))
			namespace = dict(SANDBOX, **module_names(function.__globals__))
			try:
				exec(compile(module, f"<prediction of {cls.__name__}.{name}>", "exec"), namespace)
				_compiled[key] = namespace[definition.name]
			except Exception:
				pass

	if _compiled[key] is None:
		raise Unpredictable(f"{name}() can't be compiled")

	return _compiled[key]


def is_plain(value):
	"""Whether `value` is plain data, all the way down."""

	stack = [value]
	while stack:
		value = stack.pop()
		kind = type(value)
		if kind in PLAIN:
			continue
		if kind is dict:
			stack.extend(value.keys())
			stack.extend(value.values())
		elif kind in CONTAINERS:
			stack.extend(value)
		else:
			return False

	return True


def copy_value(value):

	return value if type(value) in ATOMIC else deepcopy(value)


class Handler:
	"""A callback bound in a component's render that can run ahead of time."""


	def __init__(self, component, method, uses, takes_event=False, arguments=None):

		self.component = component
		self.method = method  # the component's method it runs
		self.uses = uses  # what it uses besides State: "value", "form", "data"
		self.takes_event = takes_event  # (a method bound directly) whether it takes the event
		self.arguments = arguments  # (otherwise) gives the method's arguments, from the event
		self.name = None  # the event id, without the component's prefix
		self.choices = None  # the values the event can have, when it reads event.value


	def options(self):
		"""[(key of the edge, value of the event)] to predict it for."""

		if self.choices is None:
			return [(None, None)]

		return [(choice_key(choice), choice) for choice in self.choices]


	def call(self, event):

		function = compiled(type(self.component), self.method)
		if self.arguments is not None:
			return function(self.component, *self.arguments(event))
		if self.takes_event:
			return function(self.component, event)

		return function(self.component)


def choice_key(value):
	"""The key of an edge for an event value, as core.js writes it (JSON.stringify)."""

	return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def handler_for(component, callback):
	"""A Handler for `callback`, bound in `component`'s render, if it can run ahead of time: a
	predictable method of the component, a lambda that only calls one with plain values, or a
	functools.partial of one with plain arguments."""

	cls = type(component)
	if getattr(callback, "__self__", None) is component:
		name = getattr(callback, "__name__", None)
		handlers = analysis(cls)[0]
		if name not in handlers or getattr(cls, name, None) is not getattr(callback, "__func__", None):
			return None
		return Handler(component, name, handlers[name], takes_event=takes_argument(callback))

	if isinstance(callback, functools.partial):
		return partial_handler(component, callback)

	if not isinstance(callback, types.FunctionType) or callback.__name__ != "<lambda>":
		return None

	call = lambda_calls(callback.__code__)
	if call is None or lambda_value(callback, call.target) is not component:
		return None
	method = analysis(cls)[1].get(call.method)
	if method is None or method[0] != call.count:
		return None

	values = {}
	for name in call.names:
		value = lambda_value(callback, name)
		if not is_plain(value):
			return None
		values[name] = value

	def arguments(event):
		namespace = dict(SANDBOX, **{name: copy_value(value) for name, value in values.items()})
		if call.event is not None:
			namespace[call.event] = event
		return eval(call.code, namespace)

	return Handler(component, call.method, call.uses | method[1], arguments=arguments)


def partial_handler(component, callback):

	function = callback.func
	if getattr(function, "__self__", None) is not component or callback.keywords:
		return None
	method = analysis(type(component))[1].get(getattr(function, "__name__", None))
	if method is None or method[0] != len(callback.args) or not is_plain(callback.args):
		return None

	values = callback.args

	return Handler(component, function.__name__, method[1], arguments=lambda event: tuple(copy_value(value) for value in values))


def predictable_callback(component, callback):
	"""Whether `callback`, bound in `component`'s render, can run ahead of time (for elements
	with a few values, when it reads event.value)."""

	return handler_for(component, callback) is not None


class LambdaCall:
	"""What a predictable lambda calls: `target.method(arguments)`."""


	def __init__(self, target, method, count, code, event, uses, names):

		self.target = target  # the name of the component in the lambda
		self.method = method
		self.count = count
		self.code = code  # evaluates the arguments (see Instrument)
		self.event = event  # the name of the event parameter, if any
		self.uses = uses  # "value", "form"
		self.names = names  # the variables the arguments read


def lambda_calls(code):
	"""For a lambda that only calls a method with plain values (`lambda event, i=i: self.pick(i)`),
	a LambdaCall, otherwise None. A lambda is found by its line, so when several on that line
	could be it, all of them must qualify and call the same thing."""

	if code in _lambdas:
		return _lambdas[code]

	call = None
	parameters = list(code.co_varnames[:code.co_argcount])
	candidates = [node for node in lambdas_at(code.co_filename, code.co_firstlineno) if lambda_parameters(node) == parameters]
	# Of several, those that call a method the code names (`self.toggle` names "toggle")
	candidates = [
		node for node in candidates
		if not isinstance(node.body, ast.Call) or not isinstance(node.body.func, ast.Attribute) or node.body.func.attr in code.co_names
	]
	if candidates and len({ast.dump(node) for node in candidates}) == 1:
		call = lambda_call(candidates[0], code)

	_lambdas[code] = call

	return call


def lambdas_at(filename, line):

	found = _sources.get(filename)
	if found is None:
		found = {}
		try:
			tree = ast.parse("".join(linecache.getlines(filename)))
		except (SyntaxError, ValueError):
			tree = None
		for node in ast.walk(tree) if tree else ():
			if isinstance(node, ast.Lambda):
				found.setdefault(node.lineno, []).append(node)
		_sources[filename] = found

	return found.get(line, [])


def lambda_parameters(node):

	arguments = node.args
	if arguments.vararg or arguments.kwarg or arguments.kwonlyargs or getattr(arguments, "posonlyargs", None):
		return None

	return [argument.arg for argument in arguments.args]


def lambda_call(node, code):

	body = node.body
	if not (
		isinstance(body, ast.Call) and not body.keywords
		and isinstance(body.func, ast.Attribute) and isinstance(body.func.value, ast.Name)
	):
		return None

	# Arguments may read parameters with defaults and variables of the enclosing function,
	# never globals, and of the event (a parameter without a default) only .value and .form[...]
	parameters = [argument.arg for argument in node.args.args]
	required = parameters[:len(parameters) - len(node.args.defaults)]
	if len(required) > 1:
		return None
	target = body.func.value.id
	readable = (set(parameters[len(required):]) | set(code.co_freevars)) - {target}
	checker = Checker(None, set(), event=required[0] if required else None, params=readable)
	if target not in set(parameters[len(required):]) | set(code.co_freevars):
		return None
	if not all(checker.expression(argument) for argument in body.args):
		return None

	arguments = ast.Tuple(elts=[deepcopy(argument) for argument in body.args], ctx=ast.Load())
	expression = ast.fix_missing_locations(ast.Expression(body=Instrument(None).visit(arguments)))
	names = sorted({child.id for child in ast.walk(arguments) if isinstance(child, ast.Name)} & readable)

	return LambdaCall(
		target, body.func.attr, len(body.args), compile(expression, "<prediction of a lambda>", "eval"),
		checker.event, frozenset(checker.uses), names,
	)


def lambda_value(function, name):
	"""The value of a lambda's variable `name`: from the enclosing function, or a default."""

	code = function.__code__
	if name in code.co_freevars:
		try:
			return function.__closure__[code.co_freevars.index(name)].cell_contents
		except (TypeError, ValueError):
			return None

	parameters = code.co_varnames[:code.co_argcount]
	defaults = function.__defaults__ or ()
	offset = len(parameters) - len(defaults)
	if name in parameters and parameters.index(name) >= offset:
		return defaults[parameters.index(name) - offset]

	return None


def choices_of(element):
	"""The values an element's events can have (event.value), when there are only a few: a
	<select>'s options, a checkbox's checked or not. Elements that aren't fields send none (None);
	None if it could be anything (a text field)."""

	tag = getattr(element, "__tag__", None)
	attributes = getattr(element, "__attributes__", {})
	if tag == "select":
		values = []
		for option in options_of(element):
			value = option.__attributes__.get("value")
			if value is None:
				# The browser's value of an option without one: its text, with spaces collapsed
				texts = [option.__inner__ or ""] + [child for child in option.__children__ if isinstance(child, str)]
				value = " ".join("".join(str(text) for text in texts).split())
			if str(value) not in values:
				values.append(str(value))
		return values if 0 < len(values) <= MAX_CHOICES else None
	if tag == "input":
		kind = str(attributes.get("type") or "text").lower()
		if kind == "checkbox":
			return [True, False]
		if kind == "radio":
			return [True]  # a radio button only changes when it's checked
		if kind in ("button", "submit", "reset"):
			return [str(attributes.get("value") or "")]
		return None
	if tag == "textarea":
		return None
	if tag == "button":
		value = attributes.get("value")
		return [None if value is None else str(value)]

	return [None]


def options_of(element):

	for child in element.__children__:
		tag = getattr(child, "__tag__", None)
		if tag == "option":
			yield child
		elif tag == "optgroup":
			yield from options_of(child)


def own_callbacks(component, bound, elements=None):
	"""Of the events `component`'s render bound ([(event id, callback)]), Handlers for those that
	can run ahead of time, named by their event id without the component's prefix. `elements`
	({event id: (element, callback)}, the page's events) tells what values an event can have."""

	if not bound:
		return []

	prefix = f"event-{component.id()}-"
	found = []
	for event_id, callback in bound:
		handler = handler_for(component, callback)
		if handler is None:
			continue
		if "value" in handler.uses:
			event = (elements or {}).get(event_id)
			handler.choices = choices_of(event[0]) if event else None
			if handler.choices is None:
				continue
		handler.name = event_id[len(prefix):] if event_id.startswith(prefix) else event_id
		found.append(handler)

	return found


def takes_argument(callback):
	"""accepts_argument() for a method or lambda, from its code: inspect.signature is slow."""

	code = getattr(getattr(callback, "__func__", callback), "__code__", None)
	if code is None:
		return accepts_argument(callback)

	positional = code.co_argcount - (1 if hasattr(callback, "__func__") else 0)

	return positional > 0 or bool(code.co_flags & inspect.CO_VARARGS)


def state_list(component):
	"""The component's own State objects, in a fixed order."""

	cls = type(component)
	names = _state_lists.get(cls)
	if names is None:
		names = _state_lists[cls] = [name for name in sorted(state_names(cls)) if isinstance(getattr(cls, name, None), State)]

	return [getattr(cls, name)._of(component) for name in names]


def overlay(states, values):
	"""A prediction overlay holding these values, copied so a handler can't change them in place
	(`self.items.append(x)` would change the real list)."""

	return {state: copy_value(value) for state, value in zip(states, values)}


def run(handler, states, values, choice=None, slots=None):
	"""(The state values after `handler`, run from `values` without changing anything, {form
	field: number of its Placeholder}), or None."""

	event = PredictedEvent(choice, slots)
	_steps.left = MAX_STEPS
	try:
		with reactive.predicting(overlay(states, values)) as changed:
			handler.call(event)
	except Exception:
		# A prediction is only a preview; the real handler still runs on click
		return None

	return tuple(changed[state] for state in states), event.form.fields


def edge(index, fields):
	"""An edge as core.js reads it: the state's index, or with the numbers of the Placeholders
	core.js fills in from the form's fields."""

	return {"to": index, "form": fields} if fields else index


def put(row, name, key, value):

	if key is None:
		row[name] = value
	else:
		row.setdefault(name, {"value": {}})["value"][key] = value


def graph(component, callbacks, render, limit=None, budget=None, elements=None):
	"""The states the component's predictable handlers reach from its current one, for core.js:
	{"states": [html per state], "edges": [{event: edge} per state]}. State 0 is the current
	one, whose HTML the browser already has (null here); a state whose HTML another state
	already has refers to it by its index, and a large state may be a patch (a list, see
	domino.patches) against the state whose index is "base". Event ids leave out the component's
	prefix ("event-<id>-"), which is the same for all of them. An edge is a state's index, or
	{"to": index, "form": {field: number}} when that state has Placeholders for the form's
	fields, or {"value": {value as JSON: edge}} for an event predicted per value.

	When more than `limit` states are reachable, or their HTML is longer than `budget`, only the
	states one event away are included, with edges from state 0 alone (and from the states a
	form submission leads to, for submitting it again). `callbacks` are those of the current
	render (see own_callbacks); `render(overlay)` renders the component with its State values
	from the overlay and returns (html, events it bound). Returns None when there's nothing to
	predict."""

	states = state_list(component)
	if not callbacks or not all(is_plain(state._value) for state in states):
		return None

	limit = MAX_STATES if limit is None else limit
	budget = MAX_BYTES if budget is None else budget
	uses = set().union(*(handler.uses for handler in callbacks))
	current = tuple(state._value for state in states)
	if "data" in uses:
		# What the handlers write to collections, as part of the state (see domino.reactive)
		states = states + [DATA]
		current = current + ((),)
	if not states:
		return None
	slots = itertools.count()

	def successors(values, callbacks):
		for handler in callbacks:
			for key, choice in handler.options():
				result = run(handler, states, values, choice, slots)
				if result is not None:
					yield handler.name, key, result[0], result[1]

	# Handlers that write to collections or read form fields make a new state every time, so
	# they're followed one step from the current state only (see below)
	def plain(callbacks):
		return [handler for handler in callbacks if not handler.uses & {"data", "form"}]

	# First follow the current render's handlers, which costs no renders, to see whether the
	# states are few (a state can bind other handlers; rendering it below finds those)
	seen = {repr(current)}
	queue = [current]
	few = limit > 1 and bool(plain(callbacks))
	while few and queue:
		for _, _, after, _ in successors(queue.pop(0), plain(callbacks)):
			key = repr(after)
			if key in seen:
				continue
			if len(seen) >= limit:
				few = False
				break
			seen.add(key)
			queue.append(after)

	rendered = {}  # repr of the values -> (html, callbacks), or None if rendering failed

	def render_state(values):
		key = repr(values)
		if key not in rendered:
			try:
				html, bound = render(overlay(states, values))
				rendered[key] = (html, own_callbacks(component, bound, elements))
			except Exception:
				rendered[key] = None
		return rendered[key]

	if few:
		result = Graph()
		index = {repr(current): 0}
		pending = [(current, callbacks)]
		while pending is not None and len(result.edges) < len(pending):
			values, own = pending[len(result.edges)]
			row = {}
			for name, choice, after, fields in successors(values, plain(own)):
				key = repr(after)
				if key not in index:
					state = render_state(after)
					if state is None:
						continue
					index[key] = result.add(state[0])
					if len(pending) >= limit or result.size > budget:
						pending = None
						break
					pending.append((after, state[1]))
				put(row, name, choice, edge(index[key], fields))
			result.edges.append(row)
		if pending is not None:
			if len(plain(callbacks)) == len(callbacks):
				if not any(result.edges):
					return None
				return result.data()
			# The others, one step from the current state
			rows = dict(enumerate(result.edges))
			pending = [(0, current, [handler for handler in callbacks if handler not in plain(callbacks)], 0)]
		else:
			few = False

	# Too many states: just the next step from the current one, and from where a form submission
	# leads, the next submission (twice), so sending a few messages in a row shows each at once
	if not few:
		result = Graph()
		index = {repr(current): 0}
		rows = {0: {}}
		pending = [(0, current, callbacks, 0)]
	while pending:
		at, values, own, depth = pending.pop(0)
		if depth:
			own = [handler for handler in own if "form" in handler.uses]
		for name, choice, after, fields in successors(values, own):
			key = repr(after)
			if key not in index:
				if len(result.states) > MAX_PREDICTIONS or result.size > budget:
					continue
				state = render_state(after)
				if state is None:
					continue
				index[key] = result.add(state[0])
				if fields and depth < CHAIN:
					rows[index[key]] = {}
					pending.append((index[key], after, state[1], depth + 1))
			put(rows[at], name, choice, edge(index[key], fields))
	if not rows[0]:
		return None
	# Only as many rows as there are states with edges (all of them in a whole graph)
	count = max([len(result.edges)] + [at + 1 for at, row in rows.items() if row])
	result.edges = [rows.get(at, {}) for at in range(count)]

	return result.data()


class Graph:
	"""States as graph() ships them, each HTML once, large ones as patches."""


	def __init__(self):

		self.states = [None]
		self.edges = []
		self.size = 0  # of the states as sent
		self.html = {}  # html -> index of the first state that has it
		self.patches = {}  # index -> patch against the first state
		self.base = None  # the index of the first state


	def add(self, html):

		index = len(self.states)
		if html in self.html:
			self.states.append(self.html[html])
			return index

		self.html[html] = index
		self.states.append(html)

		# States usually differ in a line or two (one item of a list toggled, say), so a large
		# one is sent as a patch against the first, which core.js applies (see domino.patches)
		ops = None
		if self.base is None:
			self.base = index
		elif len(self.states[self.base]) >= patches.MIN_SIZE:
			ops = patches.diff(self.states[self.base], html)
		if ops is None:
			self.size += len(html)
		else:
			self.patches[index] = ops
			self.size += sum(len(op) if isinstance(op, str) else patches.COPY_COST for op in ops)

		return index


	def data(self):

		if not self.patches:
			return {"states": self.states, "edges": self.edges}

		states = list(self.states)
		for index, ops in self.patches.items():
			states[index] = ops

		return {"states": states, "edges": self.edges, "base": self.base}


# Explaining ------------------------------------------------------------------------------------


def explain(component, callback, element=None):
	"""Why `callback`, bound in `component`'s render (to `element`, if given), isn't run ahead of
	time, or None if it is. Only for the inspector in debug mode (see domino.devtools), so it can
	take its time."""

	cls = type(component)
	if getattr(cls, "optimistic", True) is False:
		return f"{cls.__name__} sets optimistic = False"

	states = state_names(cls)
	nothing = f"{cls.__name__} has no State attributes, so there's nothing to predict"
	owner = getattr(callback, "__self__", None)
	if owner is not None and owner is not component:
		if type(owner) is cls:
			return f"it's a method of another {cls.__name__}, not of this one"
		return f"it's a method of {type(owner).__name__}, not of {cls.__name__}"
	if isinstance(callback, functools.partial) and getattr(callback.func, "__self__", None) is not component:
		return "the partial calls something other than a method of this component"

	call = None
	if isinstance(callback, types.FunctionType) and callback.__name__ == "<lambda>":
		call = lambda_calls(callback.__code__)
		if call is None:
			return "the lambda does more than call a method of the component with plain values (its defaults or variables, event.value or event.form[...])"
		other = lambda_value(callback, call.target)
		if other is not component:
			whose = f" of {type(other).__name__}" if other is not None else ""
			return f"the lambda calls {call.target}.{call.method}(){whose}, not a method of this {cls.__name__}"
	elif owner is None and not isinstance(callback, functools.partial):
		return "only the component's own methods, and lambdas that call one, are predicted"

	for name in sorted(states):
		value = getattr(cls, name)._of(component)._value
		if not is_plain(value):
			return f"{cls.__name__}.{name} holds {value_type(value)}, not plain data (numbers, strings, lists, dicts, ...)"

	handler = handler_for(component, callback)
	if handler is not None and not states and "data" not in handler.uses:
		return nothing
	if handler is not None:
		if "value" in handler.uses and (element is None or choices_of(element) is None):
			if element is None:
				return "it reads event.value, which is known ahead only for elements with a few values, like a <select> or a checkbox"
			return f"it reads event.value, and the <{element.__tag__}> it's bound to can have any value (only elements with a few values, like a <select> or a checkbox, are predicted per value)"
		return None

	if owner is not None:
		return method_reason(callback.__func__, states, cls)

	if isinstance(callback, functools.partial):
		function = callback.func
		if callback.keywords or not is_plain(callback.args):
			return "the partial passes keyword arguments, or values that aren't plain data"
		return f"the partial calls {function.__name__}(), and " + method_reason(function.__func__, states, cls, read_parameters=True)

	for name in call.names:
		if not is_plain(lambda_value(callback, name)):
			return f"the lambda passes {name}, which holds {value_type(lambda_value(callback, name))}, not plain data"

	function = getattr(cls, call.method, None)
	if not isinstance(function, types.FunctionType):
		return f"the lambda calls {call.method}(), which isn't a plain method of {cls.__name__}"
	method = analysis(cls)[1].get(call.method)
	if method is not None and method[0] != call.count:
		return f"the lambda calls {call.method}() with {call.count} argument(s), but it takes {method[0]}"

	return f"the lambda calls {call.method}(), and " + method_reason(function, states, cls, read_parameters=True)


def value_type(value):

	kind = type(value)
	article = "an" if kind.__name__[:1].lower() in "aeiou" else "a"

	return f"{article} {kind.__name__}"


def method_reason(function, states, cls, read_parameters=False):
	"""What keeps a method from being predicted: its first statement that isn't allowed."""

	name = getattr(function, "__name__", "it")
	definition = parse_function(function)
	if definition is None:
		return f"{name}() can't be read: its source is missing, or it has decorators, *args, **kwargs or keyword-only parameters"

	arguments = definition.args
	if read_parameters and arguments.defaults:
		return f"{name}() has parameters with defaults"
	checker = method_checker(function, definition, states, callable_methods(cls), read_parameters)
	if checker is None:
		return f"{name}() takes more than the event"

	if checker.function(definition):
		# Its own code is fine, so a method it calls isn't (or it isn't predictable as a handler)
		for called in sorted(checker.calls):
			if called not in analysis(cls)[1]:
				return f"{name}() calls self.{called}(), and " + method_reason(getattr(cls, called), states, cls, read_parameters=True)
		return f"{name}() isn't predictable"

	statement = checker.node
	for top in definition.body:
		if any(node is checker.node for node in ast.walk(top)):
			statement = top
			break
	line = function.__code__.co_firstlineno + getattr(statement, "lineno", 1) - 1
	try:
		code = ast.unparse(statement).split("\n")[0]
	except Exception:
		code = type(statement).__name__
	if len(code) > 60:
		code = code[:57] + "..."
	reason = checker.reason
	if reason.startswith("it calls self.") and "isn't a predictable method" in reason:
		called = reason.split("self.", 1)[1].split("()", 1)[0]
		target = getattr(cls, called, None)
		if isinstance(target, types.FunctionType) and called not in analysis(cls)[1]:
			reason += ": " + method_reason(target, states, cls, read_parameters=True)

	return f"{name}() line {line}, `{code}`: {reason}"


def script_json(graph):
	"""The graph as JSON that's safe inside a <script> element. HTML is mostly tags, so rather
	than escape every <, escape only what could end the script ("</") or open a comment."""

	return json.dumps(graph, separators=(",", ":")).replace("</", "<\\/").replace("<!--", "\\u003c!--")
