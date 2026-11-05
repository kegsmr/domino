"""Optimistic updates: which handlers can be run ahead of time to predict a component's next look.

A handler qualifies when it only changes the component's own State attributes, using plain
expressions (arithmetic, comparisons, f-strings, list/tuple literals, a few builtins) of constants
and those attributes, possibly inside if/else. So does a lambda that only calls such a method of
the component with plain values (`lambda event, index=index: self.select(index)`). Running it can
then have no effect outside the component. Anything else (database writes, calls, other objects)
is never run ahead of time.

The server follows those handlers from the component's current state to every state they reach,
renders each state once, and ships them with which event leads where (see graph()). The browser
then shows the result of any number of clicks the moment they happen, while the events still go
to the server in order and its answers confirm or correct what's shown. When the states are too
many (a counter can go up forever), it ships just the states one click away.
"""

import ast
import inspect
import json
import linecache
import textwrap
import types
from copy import deepcopy

from . import patches, reactive
from .reactive import State
from .util import accepts_argument


# Plain functions allowed in a predictable handler: they have no side effects
SAFE_CALLS = {"len", "min", "max", "abs", "round", "str", "int", "float", "bool", "sorted", "sum"}

SAFE_EXPRESSIONS = (
	ast.Constant, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
	ast.JoinedStr, ast.FormattedValue, ast.Tuple, ast.List, ast.Subscript, ast.Slice,
	ast.operator, ast.unaryop, ast.boolop, ast.cmpop, ast.expr_context,
)

# Predictions cost a render each, so one step ahead shows at most this many states
MAX_PREDICTIONS = 8

# The whole graph is shipped only when the states it reaches are at most this many (counting the
# current one; a class sets its own with `optimistic_states = n`) and their HTML at most this long
MAX_STATES = 16
MAX_BYTES = 32 * 1024

# Values a prediction can share with the real state instead of copying
ATOMIC = (int, float, complex, str, bytes, bool, type(None))

_methods = {}  # class -> names of its predictable methods
_callable = {}  # class -> {name: number of parameters} of the methods a predictable lambda may call
_lambdas = {}  # lambda code object -> [(target name, method name, number of arguments)], or None
_sources = {}  # file name -> {line: [ast.Lambda nodes starting there]}
_state_lists = {}  # class -> its State attribute names, sorted


def state_names(cls):
	"""Names of the State attributes of a component class (including inherited ones)."""

	names = set()
	for base in cls.__mro__:
		for name, value in vars(base).items():
			if isinstance(value, State):
				names.add(name)

	return names


def predictable_methods(cls):
	"""Names of the methods of `cls` that are safe to run ahead of time (computed once per class)."""

	if cls not in _methods:
		analyze(cls)

	return _methods[cls]


def callable_methods(cls):
	"""{name: number of parameters} of the methods of `cls` a predictable lambda may call: like
	predictable methods, but their parameters (all required) may be read."""

	if cls not in _callable:
		analyze(cls)

	return _callable[cls]


def analyze(cls):

	states = state_names(cls)
	direct = set()
	called = {}
	if states:
		for name, function in inspect.getmembers(cls, inspect.isfunction):
			if name.startswith("_") or name in ("render", "init"):
				continue
			definition = parse_function(function)
			if definition is None:
				continue
			if is_predictable(definition, states):
				direct.add(name)
			count = parameters_if_predictable(definition, states)
			if count is not None:
				called[name] = count

	_callable[cls] = called
	_methods[cls] = direct


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


def is_predictable(definition, states):

	# self, plus at most an event argument the handler doesn't use (it's unknown in advance)
	arguments = definition.args
	self_name = arguments.args[0].arg
	unused = {argument.arg for argument in arguments.args[1:]}
	if len(unused) > 1:
		return False

	checker = Checker(self_name, states, unused)

	return all(checker.statement(statement) for statement in definition.body)


def parameters_if_predictable(definition, states):
	"""How many parameters (after self) the method takes, if it's predictable when they're read."""

	arguments = definition.args
	if arguments.defaults:
		return None

	params = {argument.arg for argument in arguments.args[1:]}
	checker = Checker(arguments.args[0].arg, states, set(), params)
	if not all(checker.statement(statement) for statement in definition.body):
		return None

	return len(params)


class Checker:


	def __init__(self, self_name, states, unused, params=()):

		self.self_name = self_name
		self.states = states
		self.unused = unused
		self.params = params  # names that may be read (a method's parameters)


	def statement(self, node):

		if isinstance(node, ast.Pass):
			return True
		if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
			return True  # a docstring
		if isinstance(node, (ast.Assign, ast.AugAssign)):
			targets = node.targets if isinstance(node, ast.Assign) else [node.target]
			return all(self.state_attribute(target) for target in targets) and self.expression(node.value)
		if isinstance(node, ast.If):
			return (
				self.expression(node.test)
				and all(self.statement(child) for child in node.body)
				and all(self.statement(child) for child in node.orelse)
			)

		return False


	def state_attribute(self, node):

		return (
			isinstance(node, ast.Attribute)
			and isinstance(node.value, ast.Name)
			and node.value.id == self.self_name
			and node.attr in self.states
		)


	def expression(self, node):

		if self.state_attribute(node):
			return True
		if isinstance(node, ast.Call):
			return (
				isinstance(node.func, ast.Name)
				and node.func.id in SAFE_CALLS
				and not node.keywords
				and all(self.expression(argument) for argument in node.args)
			)
		if isinstance(node, ast.Name):
			# Only the builtins above (as call targets) and parameters that may be read;
			# never the unused event argument
			return node.id in self.params and isinstance(node.ctx, ast.Load)
		if not isinstance(node, SAFE_EXPRESSIONS):
			return False

		return all(self.expression(child) for child in ast.iter_child_nodes(node))


def predictable_callback(component, callback):
	"""Whether `callback`, bound in `component`'s render, can run ahead of time: a predictable
	method of the component, or a lambda that only calls one with plain values."""

	# on-click="remove(item)" in a Domino template: one of the component's methods, with values
	call = getattr(callback, "__domino_call__", None)
	if call is not None:
		method, args = call
		return getattr(method, "__self__", None) is component and callable_methods(type(component)).get(method.__name__) == len(args)

	if getattr(callback, "__self__", None) is component:
		return getattr(callback, "__name__", None) in predictable_methods(type(component))

	if not isinstance(callback, types.FunctionType) or callback.__name__ != "<lambda>":
		return False

	calls = lambda_calls(callback.__code__)
	if not calls:
		return False

	methods = callable_methods(type(component))
	for target, method, count in calls:
		if methods.get(method) != count or lambda_value(callback, target) is not component:
			return False

	return True


def lambda_calls(code):
	"""For a lambda that only calls a method with plain values (`lambda event, i=i: self.pick(i)`),
	[(name of the object called, method name, number of arguments)], otherwise None. A lambda is
	found by its line, so when several on that line could be it, all of them must qualify."""

	if code in _lambdas:
		return _lambdas[code]

	calls = None
	parameters = list(code.co_varnames[:code.co_argcount])
	candidates = [node for node in lambdas_at(code.co_filename, code.co_firstlineno) if lambda_parameters(node) == parameters]
	if candidates:
		calls = [lambda_call(node, code) for node in candidates]
		if any(call is None for call in calls):
			calls = None

	_lambdas[code] = calls

	return calls


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
	# never the event (it's unknown in advance) or globals
	parameters = [argument.arg for argument in node.args.args]
	readable = set(parameters[len(parameters) - len(node.args.defaults):]) | set(code.co_freevars)
	target = body.func.value.id
	checker = Checker(None, set(), set(), readable)
	if target not in readable or not all(checker.expression(argument) for argument in body.args):
		return None

	return (target, body.func.attr, len(body.args))


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


def own_callbacks(component, bound):
	"""Of the events `component`'s render bound ([(event id, callback)]), those that can run ahead
	of time, as [(event id without the component's prefix, callback, whether it takes the event)]."""

	if not bound or not state_list(component):
		return []

	prefix = f"event-{component.id()}-"
	found = []
	for event_id, callback in bound:
		if predictable_callback(component, callback):
			name = event_id[len(prefix):] if event_id.startswith(prefix) else event_id
			found.append((name, callback, takes_argument(callback)))

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

	return [getattr(cls, name)._of(component) for name in sorted_state_names(cls)]


def sorted_state_names(cls):
	"""Names of the class's State attributes, in a fixed order, worked out once per class."""

	names = _state_lists.get(cls)
	if names is None:
		names = _state_lists[cls] = [name for name in sorted(state_names(cls)) if isinstance(getattr(cls, name, None), State)]

	return names


def overlay(states, values):
	"""A prediction overlay holding these values, copied so a handler can't change them in place
	(`self.items += [x]` would change the real list)."""

	return {state: value if type(value) in ATOMIC else deepcopy(value) for state, value in zip(states, values)}


def run(callback, takes_event, states, values):
	"""The state values after `callback`, run from `values` without changing anything, or None."""

	try:
		with reactive.predicting(overlay(states, values)) as changed:
			if takes_event:
				callback(None)
			else:
				callback()
	except Exception:
		# A prediction is only a preview; the real handler still runs on click
		return None

	return tuple(changed[state] for state in states)


def graph(component, callbacks, render, limit=None, budget=None):
	"""The states the component's predictable handlers reach from its current one, for core.js:
	{"states": [html per state], "edges": [{event: state index} per state]}. State 0 is the
	current one, whose HTML the browser already has (null here); a state whose HTML another
	state already has refers to it by its index, and a large state may be a patch (a list, see
	domino.patches) against the state whose index is "base". Event ids leave out the component's prefix
	("event-<id>-"), which is the same for all of them.

	When more than `limit` states are reachable, or their HTML is longer than `budget`, only the
	states one event away are included, with edges from state 0 alone. `callbacks` are those of
	the current render (see own_callbacks); `render(overlay)` renders the component with its
	State values from the overlay and returns (html, events it bound). Returns None when there's
	nothing to predict."""

	states = state_list(component)
	if not states or not callbacks:
		return None

	limit = MAX_STATES if limit is None else limit
	budget = MAX_BYTES if budget is None else budget
	current = tuple(state._value for state in states)

	def successors(values, callbacks):
		for name, callback, takes_event in callbacks:
			after = run(callback, takes_event, states, values)
			if after is not None:
				yield name, after

	# First follow the current render's handlers, which costs no renders, to see whether the
	# states are few (a state can bind other handlers; rendering it below finds those)
	seen = {repr(current)}
	queue = [current]
	few = limit > 1
	while few and queue:
		for _, after in successors(queue.pop(0), callbacks):
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
				rendered[key] = (html, own_callbacks(component, bound))
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
			for name, after in successors(values, own):
				key = repr(after)
				if key not in index:
					state = render_state(after)
					if state is None:
						continue
					size = 0 if state[0] in result.html else len(state[0])
					if len(pending) >= limit or result.size + size > budget:
						pending = None
						break
					index[key] = result.add(state[0])
					pending.append((after, state[1]))
				row[name] = index[key]
			result.edges.append(row)
		if pending is not None:
			return result.data()

	# Too many states: just the next step from the current one
	result = Graph()
	index = {repr(current): 0}
	row = {}
	for name, after in successors(current, callbacks):
		key = repr(after)
		if key not in index:
			if len(result.states) > MAX_PREDICTIONS:
				continue
			state = render_state(after)
			if state is None:
				continue
			index[key] = result.add(state[0])
		row[name] = index[key]
	if not row:
		return None
	result.edges.append(row)

	return result.data()


class Graph:
	"""States as graph() ships them, each HTML once."""


	def __init__(self):

		self.states = [None]
		self.edges = []
		self.size = 0
		self.html = {}  # html -> index of the first state that has it


	def add(self, html):

		index = len(self.states)
		if html in self.html:
			self.states.append(self.html[html])
		else:
			self.html[html] = index
			self.states.append(html)
			self.size += len(html)

		return index


	def data(self):

		data = {"states": self.states, "edges": self.edges}

		# States usually differ in a line or two (one item of a list toggled, say), so a large
		# one is sent as a patch against the first, which core.js applies (see domino.patches)
		texts = [index for index, html in enumerate(self.states) if isinstance(html, str)]
		if len(texts) < 2 or len(self.states[texts[0]]) < patches.MIN_SIZE:
			return data

		base = self.states[texts[0]]
		states = list(self.states)
		for index in texts[1:]:
			ops = patches.diff(base, states[index])
			if ops is not None:
				states[index] = ops
				data = {"states": states, "edges": self.edges, "base": texts[0]}

		return data


def explain(component, callback):
	"""Why `callback`, bound in `component`'s render, isn't run ahead of time, or None if it is.
	Only for the inspector in debug mode (see domino.devtools), so it can take its time."""

	cls = type(component)
	if getattr(cls, "optimistic", True) is False:
		return f"{cls.__name__} sets optimistic = False"
	if predictable_callback(component, callback):
		return None

	states = state_names(cls)
	nothing = f"{cls.__name__} has no State attributes, so there's nothing to predict"

	# on-click="remove(item)" in a Domino template
	if hasattr(callback, "__domino_call__"):
		call = callback.__domino_call__
		if call is None:
			return "the handler takes the event, which isn't known before the click"
		method, args = call
		if getattr(method, "__self__", None) is not component:
			return f"it calls a method of {type(method.__self__).__name__}, not of this {cls.__name__}"
		if not states:
			return nothing
		return f"it calls {method.__name__}() with {len(args)} value(s), and " + method_reason(method.__func__, states, read_parameters=True)

	owner = getattr(callback, "__self__", None)
	if owner is not None:
		if owner is not component and type(owner) is cls:
			return f"it's a method of another {cls.__name__}, not of this one"
		if owner is not component:
			return f"it's a method of {type(owner).__name__}, not of {cls.__name__}"
		return method_reason(callback.__func__, states) if states else nothing

	if not isinstance(callback, types.FunctionType) or callback.__name__ != "<lambda>":
		return "only the component's own methods, and lambdas that call one, are predicted"

	calls = lambda_calls(callback.__code__)
	if not calls:
		return "the lambda does more than call a method of the component with plain values (its defaults or variables)"

	methods = callable_methods(cls)
	for target, method, count in calls:
		other = lambda_value(callback, target)
		if other is not component:
			# Lambdas are found by their line, so with several on it this can't tell which it is
			called = " or ".join(sorted({f"{name}.{function}()" for name, function, _ in calls}))
			whose = f" of {type(other).__name__}" if other is not None else ""
			return f"the lambda calls {called}{whose}, not a method of this {cls.__name__}"
		if not states:
			return nothing
		if methods.get(method) != count:
			function = getattr(cls, method, None)
			if not isinstance(function, types.FunctionType):
				return f"the lambda calls {method}(), which isn't a plain method of {cls.__name__}"
			return f"the lambda calls {method}(), and " + method_reason(function, states, read_parameters=True)

	return "it isn't a predictable method of the component"


def method_reason(function, states, read_parameters=False):
	"""What keeps a method from being predicted: its first statement that isn't a plain change of
	the component's own State."""

	name = getattr(function, "__name__", "it")
	definition = parse_function(function)
	if definition is None:
		return f"{name}() can't be read: its source is missing, or it has decorators, *args, **kwargs or keyword-only parameters"

	arguments = definition.args
	self_name = arguments.args[0].arg
	if read_parameters:
		if arguments.defaults:
			return f"{name}() has parameters with defaults"
		unused = set()
		checker = Checker(self_name, states, unused, {argument.arg for argument in arguments.args[1:]})
	else:
		unused = {argument.arg for argument in arguments.args[1:]}
		if len(unused) > 1:
			return f"{name}() takes more than the event"
		checker = Checker(self_name, states, unused)

	for statement in definition.body:
		if checker.statement(statement):
			continue
		line = function.__code__.co_firstlineno + statement.lineno - 1
		try:
			code = ast.unparse(statement).split("\n")[0]
		except Exception:
			code = type(statement).__name__
		if len(code) > 60:
			code = code[:57] + "..."
		return f"{name}() line {line}, `{code}`: {statement_reason(statement, checker, unused)}"

	return f"{name}() isn't predictable"


def statement_reason(statement, checker, unused):

	names = {node.id for node in ast.walk(statement) if isinstance(node, ast.Name)}
	if names & unused:
		return "it reads the event, which isn't known before the click"
	for node in ast.walk(statement):
		if isinstance(node, ast.Call) and not (isinstance(node.func, ast.Name) and node.func.id in SAFE_CALLS):
			try:
				called = ast.unparse(node.func)
			except Exception:
				called = "a function"
			return f"it calls {called}(), which could change things outside the component"
	if isinstance(statement, (ast.Assign, ast.AugAssign)):
		targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
		if not all(checker.state_attribute(target) for target in targets):
			return "it changes something other than the component's own State"
		return "it reads something other than the component's State, constants and plain expressions"
	if isinstance(statement, ast.Return):
		return "it returns a value (the component it re-renders is up to the server)"
	if isinstance(statement, (ast.For, ast.While, ast.With, ast.Try)):
		return "only assignments to State and if/else are followed, not loops, with or try"

	return "it reads something other than the component's State, constants and plain expressions"


def script_json(graph):
	"""The graph as JSON that's safe inside a <script> element. HTML is mostly tags, so rather
	than escape every <, escape only what could end the script ("</") or open a comment."""

	return json.dumps(graph, separators=(",", ":")).replace("</", "<\\/").replace("<!--", "\\u003c!--")
