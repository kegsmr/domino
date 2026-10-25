"""Forms declared once: list the fields, and Domino renders them, validates them in the browser
and on the server, shows errors next to each field and hands you typed values.

	from domino import forms

	class Signup(forms.Form):

		name = forms.Text("Name", required=True, max_length=50)
		age = forms.Integer("Age", min=13)

		def submitted(self, data):
			...  # only called with valid, typed data: data.age is an int

Each field renders its native HTML constraints (required, min, max, maxlength, pattern,
type=email), so the browser checks them before anything is sent; the server checks them again
on submit, since the browser can't be trusted. Signup.validate_data(event.form) does the same
checks in any handler, without the component.
"""

import datetime
import math
import re

from . import tags as t
from .core import Element
from .reactive import State


class ValidationError(ValueError):
	"""Raised by validators with a message for the user. In validate(self, data), `field` puts
	the message next to that field instead of above the form."""


	def __init__(self, message, field=None):

		super().__init__(message)
		self.message = message
		self.field = field


class Data(dict):
	"""Valid, typed values by field name, also readable as attributes: data.age."""


	def __getattr__(self, name):

		try:
			return self[name]
		except KeyError:
			raise AttributeError(name) from None


def run_validator(validator, *args):

	# A validator raises ValidationError, or returns a message (a non-empty string) when it fails
	message = validator(*args)
	if isinstance(message, str) and message:
		raise ValidationError(message)


class Field:
	"""A form field, declared as a class attribute of a Form. The base for the field types below."""

	input_type = "text"
	empty = None  # what an empty field's value is
	redisplay = True  # whether the value the user sent is rendered back after an error

	messages = {
		"required": "This field is required.",
	}


	def __init__(self, label=None, *, required=False, default=None, help=None, validators=(),
			live=False, debounce=300, messages=None, **attributes):

		self.name = None
		self.label_text = label
		self.required = required
		self.default = default
		self.help_text = help
		self.validators = list(validators)
		# Validate as the user goes: True (or "change") when the value changes, "blur" when
		# leaving the field, "input" while typing (after `debounce` ms)
		self.live = "change" if live is True else live
		self.debounce = debounce
		self.messages = dict(type(self).messages, **(messages or {}))
		self.attributes = attributes  # extra HTML attributes for the input, e.g. autocomplete=


	def __set_name__(self, owner, name):

		self.name = name
		if self.label_text is None:
			self.label_text = name.replace("_", " ").capitalize()


	def __get__(self, instance, owner):

		# A descriptor, so components don't render it as an HTML attribute
		return self


	def message(self, key, **values):

		return self.messages[key].format(**values)


	def raw(self, form):
		"""This field's submitted text in `form` (event.form, or any dict of strings)."""

		value = form.get(self.name, "")
		# A repeated name arrives as a list; the last one wins, like most frameworks
		if isinstance(value, list):
			value = value[-1] if value else ""

		return "" if value is None else str(value)


	def clean(self, raw):
		"""The typed value for `raw`, or ValidationError."""

		if raw.strip() == "":
			if self.required:
				raise ValidationError(self.message("required"))
			return self.empty

		value = self.convert(raw)
		self.check(value)

		return value


	def convert(self, raw):

		return raw


	def check(self, value):

		pass


	def format(self, value):
		"""The text an input shows for a typed value."""

		return "" if value is None else str(value)


	def constraints(self):
		"""HTML attributes the browser validates with."""

		return {"type": self.input_type, "required": self.required}


	def input(self, value, **attributes):
		"""The input showing `value` (text), with `attributes` (id, name, aria-*) first."""

		return t.input(**attributes, value=value, **self.constraints())


class Text(Field):

	messages = dict(Field.messages, **{
		"min_length": "Use at least {min_length} characters.",
		"max_length": "Use at most {max_length} characters.",
		"pattern": "Enter a value in the expected format.",
	})


	def __init__(self, label=None, *, min_length=None, max_length=None, pattern=None, strip=True, **options):

		super().__init__(label, **options)
		self.min_length = min_length
		self.max_length = max_length
		self.pattern = pattern
		self.strip = strip


	def convert(self, raw):

		return raw.strip() if self.strip else raw


	def check(self, value):

		if self.min_length is not None and len(value) < self.min_length:
			raise ValidationError(self.message("min_length", min_length=self.min_length))
		if self.max_length is not None and len(value) > self.max_length:
			raise ValidationError(self.message("max_length", max_length=self.max_length))
		# Browsers match the whole value too
		if self.pattern is not None and not re.fullmatch(self.pattern, value):
			raise ValidationError(self.message("pattern"))


	def clean(self, raw):

		value = super().clean(raw)

		# An empty text field is "", not None
		return "" if value is None else value


	def constraints(self):

		return dict(
			super().constraints(),
			minlength=self.min_length,
			maxlength=self.max_length,
			pattern=self.pattern
		)


class TextArea(Text):


	def input(self, value, **attributes):

		constraints = self.constraints()
		del constraints["type"], constraints["pattern"]

		return t.textarea(**attributes, **constraints) [
			value
		]


# The browser's own check for type=email (from the HTML standard), plus a dot in the domain
EMAIL = re.compile(
	r"[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
	r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+"
)


class Email(Text):

	input_type = "email"

	messages = dict(Text.messages, email="Enter a valid email address.")


	def convert(self, raw):

		value = raw.strip()
		if not EMAIL.fullmatch(value):
			raise ValidationError(self.message("email"))

		return value


class Password(Text):
	"""Not rendered back after an error unless keep=True, so it isn't in the page's HTML."""

	input_type = "password"


	def __init__(self, label=None, *, keep=False, strip=False, **options):

		super().__init__(label, strip=strip, **options)
		self.redisplay = keep


class Number(Field):
	"""The base for Integer and Float: a type=number input with min and max."""

	input_type = "number"
	step = None

	messages = dict(Field.messages, **{
		"min": "Must be at least {min}.",
		"max": "Must be at most {max}.",
	})


	def __init__(self, label=None, *, min=None, max=None, **options):

		super().__init__(label, **options)
		self.min = min
		self.max = max


	def check(self, value):

		if self.min is not None and value < self.min:
			raise ValidationError(self.message("min", min=self.min))
		if self.max is not None and value > self.max:
			raise ValidationError(self.message("max", max=self.max))


	def constraints(self):

		return dict(super().constraints(), min=self.min, max=self.max, step=self.step)


class Integer(Number):

	messages = dict(Number.messages, invalid="Enter a whole number.")


	def convert(self, raw):

		try:
			return int(raw.strip())
		except ValueError:
			pass

		# type=number allows forms like "1e3" and "4.0"
		try:
			number = float(raw)
		except ValueError:
			number = math.nan
		if not number.is_integer():
			raise ValidationError(self.message("invalid"))

		return int(number)


class Float(Number):

	step = "any"

	messages = dict(Number.messages, invalid="Enter a number.")


	def convert(self, raw):

		try:
			number = float(raw)
		except ValueError:
			number = math.nan
		if not math.isfinite(number):
			raise ValidationError(self.message("invalid"))

		return number


class Date(Field):

	input_type = "date"

	messages = dict(Field.messages, **{
		"invalid": "Enter a valid date.",
		"min": "Must be on or after {min}.",
		"max": "Must be on or before {max}.",
	})


	def __init__(self, label=None, *, min=None, max=None, **options):

		super().__init__(label, **options)
		self.min = datetime.date.fromisoformat(min) if isinstance(min, str) else min
		self.max = datetime.date.fromisoformat(max) if isinstance(max, str) else max


	def convert(self, raw):

		try:
			return datetime.date.fromisoformat(raw.strip())
		except ValueError:
			raise ValidationError(self.message("invalid")) from None


	def check(self, value):

		if self.min is not None and value < self.min:
			raise ValidationError(self.message("min", min=self.format(self.min)))
		if self.max is not None and value > self.max:
			raise ValidationError(self.message("max", max=self.format(self.max)))


	def format(self, value):

		return value.isoformat() if isinstance(value, datetime.date) else super().format(value)


	def constraints(self):

		return dict(super().constraints(), min=self.format(self.min) or None, max=self.format(self.max) or None)


class Checkbox(Field):
	"""True when checked. required=True means it must be checked (e.g. accepting terms)."""

	input_type = "checkbox"
	empty = False

	messages = dict(Field.messages, required="Check this box to continue.")


	def raw(self, form):

		# Unchecked boxes aren't sent at all
		return "on" if self.name in form else ""


	def convert(self, raw):

		return True


	def format(self, value):

		return "on" if value else ""


	def input(self, value, **attributes):

		return t.input(**attributes, checked=bool(value), **self.constraints())


class Choice(Field):
	"""One of `choices`, shown as a <select>. Choices are values, or (value, label) pairs; the
	typed value is the choice itself (an int stays an int). Without a default the select starts
	on an empty option, `placeholder`."""

	messages = dict(Field.messages, invalid="Choose one of the options.")


	def __init__(self, choices, label=None, *, placeholder="Choose…", **options):

		super().__init__(label, **options)
		self.choices = [choice if isinstance(choice, tuple) else (choice, choice) for choice in choices]
		self.placeholder = placeholder


	def convert(self, raw):

		for value, _ in self.choices:
			if str(value) == raw:
				return value

		raise ValidationError(self.message("invalid"))


	def input(self, value, **attributes):

		options = []
		if self.default is None:
			options.append(t.option(value="", selected=value == "") [self.placeholder])
		for choice, label in self.choices:
			options.append(t.option(value=str(choice), selected=str(choice) == value) [str(label)])

		return t.select(**attributes, required=self.required)(options)


class BoundField:
	"""A field of one form, for laying a form out yourself: form.fields.email.label(),
	.input(), .help(), .error(), or .render() for all of them."""


	def __init__(self, form, field):

		self.form = form
		self.field = field
		self.name = field.name


	@property
	def id(self):

		return f"{self.form.id()}-{self.name}"


	@property
	def error_message(self):

		return self.form.errors.get(self.name)


	@property
	def value(self):
		"""The text the input shows: what the user sent (kept while there are errors), or the
		initial value."""

		field = self.field
		sent = self.form._sent
		if sent is not None:
			return field.raw(sent) if field.redisplay else ""
		if not field.redisplay:
			return ""

		return field.format(self.form.initial.get(self.name, field.default))


	def label(self, text=None, **attributes):

		return t.label(for_=self.id, **attributes) [
			text if text is not None else self.field.label_text
		]


	def input(self, **attributes):

		field = self.field
		invalid = self.error_message is not None
		described = [f"{self.id}-help"] if field.help_text else []
		if invalid:
			described.append(f"{self.id}-error")

		element = field.input(
			self.value,
			id=self.id,
			name=self.name,
			aria_invalid="true" if invalid else None,
			aria_describedby=" ".join(described) or None
		)
		element.configure(**dict(field.attributes, **attributes))

		if field.live:
			name = self.name
			debounce = field.debounce if field.live == "input" else None
			element.bind(field.live, lambda event: self.form._validate_live(name, event), debounce=debounce)

		return element


	def help(self):

		if not self.field.help_text:
			return ""

		return t.small(id=f"{self.id}-help", class_="help") [
			self.field.help_text
		]


	def error(self):

		# "" when there's none, so custom layouts can put it in their children as it is
		message = self.error_message
		if message is None:
			return ""

		return t.p(id=f"{self.id}-error", class_="error", role="alert") [
			message
		]


	def render(self):
		"""The label, input, help text and error, in a <div class="field">."""

		checkbox = isinstance(self.field, Checkbox)
		parts = [self.input(), self.label()] if checkbox else [self.label(), self.input()]
		parts += [self.help(), self.error()]

		return t.div(class_=["field", "checkbox"] if checkbox else "field")([part for part in parts if part != ""])


class Fields:
	"""A form's fields by name (form.fields.email, form.fields["email"]), in declaration order."""


	def __init__(self, form):

		self._form = form


	def __getattr__(self, name):

		field = type(self._form)._fields.get(name)
		if field is None:
			raise AttributeError(f"{type(self._form).__name__} has no field {name!r}")

		return BoundField(self._form, field)


	def __getitem__(self, name):

		try:
			return getattr(self, name)
		except AttributeError as error:
			raise KeyError(name) from error


	def __iter__(self):

		return (BoundField(self._form, field) for field in type(self._form)._fields.values())


	def __len__(self):

		return len(type(self._form)._fields)


class Option:
	"""A setting on the Form class (like submit_text), kept out of the HTML attributes."""


	def __init__(self, value):

		self.value = value


	def __get__(self, instance, owner):

		return self.value


class Form(t.form):
	"""A <form> rendered from its fields. Override submitted(self, data) to handle valid data,
	validate_<field>(self, value) and validate(self, data) to check more, and render() to lay
	it out yourself with self.fields."""

	submit_text = Option("Submit")

	# Submit handlers use the event, so there's nothing to predict
	optimistic = False

	errors = State({})  # field name (None for the whole form) -> message
	_sent = State(None)  # what the user sent, rendered back while there are errors

	_fields = {}

	css = {
		"display": "grid",
		"gap": "1rem",
		"max_width": "28rem",
		".field": {"display": "flex", "flex_direction": "column", "gap": ".3rem"},
		".field.checkbox": {"flex_direction": "row", "flex_wrap": "wrap", "align_items": "center", "gap": ".5rem"},
		"label": {"font_weight": "600"},
		".checkbox label": {"font_weight": "normal"},
		"input:not([type=checkbox]), select, textarea": {
			"font": "inherit",
			"padding": ".45rem .6rem",
			"border": "1px solid #b5b5b5",
			"border_radius": "6px",
			"[aria-invalid=true]": {"border_color": "var(--form-error, #c62828)"},
		},
		".help": {"color": "#666", "font_size": ".875rem"},
		".error": {"flex_basis": "100%", "margin": 0, "color": "var(--form-error, #c62828)", "font_size": ".875rem"},
		".form-error": {"margin": 0, "color": "var(--form-error, #c62828)"},
		"button[type=submit]": {
			"justify_self": "start",
			"font": "inherit",
			"padding": ".5rem 1.2rem",
			"border": 0,
			"border_radius": "6px",
			"background": "var(--form-accent, #2557c4)",
			"color": "#fff",
			"cursor": "pointer",
		},
		"button[data-loading]": {"opacity": ".6", "cursor": "progress"},
	}


	def __init_subclass__(cls, **kwargs):

		super().__init_subclass__(**kwargs)

		# Fields in the order they're declared, base classes' first; `name = None` removes one
		fields = {}
		for base in reversed(cls.__mro__):
			for name, value in vars(base).items():
				if isinstance(value, Field):
					if name in Form._reserved:
						raise TypeError(f"{cls.__name__}.{name}: Form already uses the name {name!r}, so a field can't")
					fields[name] = value
				elif name in fields:
					del fields[name]
		cls._fields = fields

		if "submit_text" in vars(cls) and not isinstance(vars(cls)["submit_text"], Option):
			cls.submit_text = Option(vars(cls)["submit_text"])


	def __init__(self, *, initial=None, submitted=None, submit_text=None, **kwargs):

		# Typed values the fields start with (and return to after a successful submit)
		self.initial = dict(initial or {})
		if submitted is not None:
			self.submitted = submitted
		if submit_text is not None:
			self.submit_text = submit_text
		self._collecting = None

		super().__init__(**kwargs)


	@property
	def fields(self):

		return Fields(self)


	def submitted(self, data):
		"""Called with valid, typed data after a submit. self.error() still rejects it."""


	def validate(self, data):
		"""Checks across fields, once each field is valid. Raise ValidationError (with field=
		to put it next to a field), call self.error(), or return a message."""


	def error(self, field, message):
		"""Show `message` next to `field` (or above the form for None). In submitted() this keeps
		the form as the user filled it."""

		if field is not None and field not in self._fields:
			raise KeyError(f"{type(self).__name__} has no field {field!r}")

		if self._collecting is not None:
			self._collecting.setdefault(field, message)
			return

		self.errors = {**self.errors, field: message}


	def reset(self):
		"""Back to the initial values, without errors."""

		self._sent = None
		self.errors = {}


	@classmethod
	def validate_data(cls, form):
		"""Check submitted values (event.form, or any dict of strings) without the component:
		returns (data, errors), typed data and a dict of messages by field name."""

		# Validators are methods; they get an instance that isn't set up as a component
		instance = cls.__new__(cls)
		instance._collecting = None

		return instance._validate(form)


	def _validate(self, form, only=None):

		data = Data()
		errors = {}

		self._collecting = errors
		try:
			for name, field in self._fields.items():
				if only is not None and name != only:
					continue
				raw = field.raw(form)
				try:
					value = field.clean(raw)
					# Custom checks only see values that are there
					if raw.strip():
						for validator in field.validators:
							run_validator(validator, value)
						method = getattr(self, f"validate_{name}", None)
						if method is not None:
							run_validator(method, value)
				except ValidationError as error:
					errors.setdefault(name, error.message)
				if name not in errors:
					data[name] = value

			if only is None and not errors:
				try:
					run_validator(self.validate, data)
				except ValidationError as error:
					errors.setdefault(error.field, error.message)
		finally:
			self._collecting = None

		return data, errors


	def _submit(self, event):

		data, errors = self._validate(event.form)

		result = None
		if not errors:
			self._collecting = errors
			try:
				result = self.submitted(data)
			finally:
				self._collecting = None

		# With errors the form shows what was sent; otherwise it starts over. Set after
		# submitted(), so a component it changed (a parent showing a success view) is the
		# one re-rendered
		if errors:
			self._sent = self._kept(event.form)
			self.errors = errors
		else:
			self.reset()

		return result if isinstance(result, Element) else None


	def _validate_live(self, name, event):

		_, errors = self._validate(event.form, only=name)

		# The field that fired takes what the server renders, so render what was typed
		self._sent = self._kept(event.form)
		self.errors = {**{key: message for key, message in self.errors.items() if key != name}, **errors}

		return self


	def _kept(self, form):

		# Passwords aren't rendered back, so don't keep them either
		return {
			name: value for name, value in form.items()
			if name not in self._fields or self._fields[name].redisplay
		}


	def form_error(self):

		message = self.errors.get(None)
		if message is None:
			return ""

		return t.p(class_="form-error", role="alert") [
			message
		]


	def submit_button(self):

		return t.button(type="submit") [
			self.submit_text
		]


	def render(self):

		parts = [self.form_error()]
		parts += [field.render() for field in self.fields]
		parts.append(self.submit_button())

		return [part for part in parts if part != ""]


	def _render(self, level=0, indent=4):

		# Bound on every render, so it's there whatever render() a subclass has
		self.bind("submit", self._submit)

		return super()._render(level, indent)


# Names a field can't have, since a Form (or any component) uses them
Form._reserved = frozenset(name for name in dir(Form) if not name.startswith("__"))
