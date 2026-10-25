"""Optimistic updates: which handlers can be run ahead of time to predict a component's next look.

A handler qualifies when it only changes the component's own State attributes, using plain
expressions (arithmetic, comparisons, f-strings, list/tuple literals, a few builtins) of constants
and those attributes, possibly inside if/else. Running it can then have no effect outside the
component, so the server renders "after this handler" in advance and the browser shows it the
moment the user clicks, before the server has answered. Anything else (database writes, calls,
other objects) is never run ahead of time.
"""

import ast
import inspect
import textwrap

from .reactive import State


# Plain functions allowed in a predictable handler: they have no side effects
SAFE_CALLS = {"len", "min", "max", "abs", "round", "str", "int", "float", "bool", "sorted", "sum"}

SAFE_EXPRESSIONS = (
	ast.Constant, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
	ast.JoinedStr, ast.FormattedValue, ast.Tuple, ast.List, ast.Subscript, ast.Slice,
	ast.operator, ast.unaryop, ast.boolop, ast.cmpop, ast.expr_context,
)

# Predictions cost a render each, so a component predicts at most this many handlers
MAX_PREDICTIONS = 8

_methods = {}  # class -> names of its predictable methods


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

	cached = _methods.get(cls)
	if cached is not None:
		return cached

	states = state_names(cls)
	found = set()
	if states:
		for name, function in inspect.getmembers(cls, inspect.isfunction):
			if name.startswith("_") or name in ("render", "init"):
				continue
			if is_predictable(function, states):
				found.add(name)

	_methods[cls] = found

	return found


def is_predictable(function, states):

	try:
		tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
	except (OSError, TypeError, SyntaxError):
		return False

	definition = tree.body[0]
	if not isinstance(definition, ast.FunctionDef) or definition.decorator_list:
		return False

	arguments = definition.args
	if arguments.vararg or arguments.kwarg or arguments.kwonlyargs or not arguments.args:
		return False

	# self, plus at most an event argument the handler doesn't use (it's unknown in advance)
	self_name = arguments.args[0].arg
	unused = {argument.arg for argument in arguments.args[1:]}
	if len(unused) > 1:
		return False

	checker = Checker(self_name, states, unused)

	return all(checker.statement(statement) for statement in definition.body)


class Checker:


	def __init__(self, self_name, states, unused):

		self.self_name = self_name
		self.states = states
		self.unused = unused


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
			# Only the builtins above (as call targets); never the unused event argument
			return False
		if not isinstance(node, SAFE_EXPRESSIONS):
			return False

		return all(self.expression(child) for child in ast.iter_child_nodes(node))
