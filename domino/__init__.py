"""Domino: a Python web framework on Flask, like Meteor.

What apps use is here, `from domino import Domino, Component, State`, and in the public modules
domino.tags, domino.accounts, domino.forms, domino.testing, domino.mail, domino.mongo and
domino.bootstrap. Everything else is internal (modules starting with an underscore).
"""

import importlib as _importlib
import importlib.abc as _importlib_abc
import importlib.util as _importlib_util
import sys as _sys
import warnings as _warnings

from flask import abort, g, request, session, url_for

from ._components import Document
# Documented for pages built without Document, but not in __all__
from ._components import Core, PublicSettings
from ._core import Domino, Event, redirect
# Documented for custom page stores (Domino(__name__, page_store=...)), but not in __all__
from ._core import MemoryPageStore, PageStore
from ._reactive import Collection, State, batch, wait
from ._templates import TemplateError, html, template
from . import mongo
from . import tags as t
from .tags import Component


__all__ = [
	"Domino",
	"Component", "Document", "State", "Collection", "Event",
	"redirect", "batch", "wait", "html", "template",
	"TemplateError",
	"t",
	# Flask's, for handlers and pages
	"request", "session", "g", "abort", "url_for",
]

# Modules that were public before 0.4 and are internal now: the old paths keep working for a
# release, with a DeprecationWarning
_MOVED = {
	name: f"domino._{name}" for name in (
		"core", "reactive", "templates", "dtemplates", "components", "util", "css", "optimistic",
		"patches", "hot", "workers", "devmongo", "devtools", "asgi", "pytest_plugin", "settings",
		"client", "uploads", "pages", "tailwind", "deploy", "cli",
	)
}


def _moved_message(name):

	if name == "components":
		return "domino.components is internal now: import Document from domino (from domino import Document)"

	return f"domino.{name} is internal now (domino._{name}); import what apps use from domino"


_kept = {}


class _MovedModules(_importlib_abc.MetaPathFinder, _importlib_abc.Loader):
	"""`import domino.core` gives domino._core, with a DeprecationWarning."""


	def find_spec(self, fullname, path=None, target=None):

		if fullname.startswith("domino.") and fullname[len("domino."):] in _MOVED:
			return _importlib_util.spec_from_loader(fullname, self)

		return None


	def create_module(self, spec):

		name = spec.name[len("domino."):]
		_warnings.warn(_moved_message(name), DeprecationWarning, stacklevel=2)
		module = _importlib.import_module(_MOVED[name])
		# The import system sets these on the module it gets; they stay the private module's
		_kept[spec.name] = (module.__spec__, module.__loader__)

		return module


	def exec_module(self, module):

		module.__spec__, module.__loader__ = _kept.pop(module.__spec__.name)


_sys.meta_path.insert(0, _MovedModules())


def __getattr__(name):

	# domino.core and the other moved modules, as attributes
	if name in _MOVED:
		return _importlib.import_module(f"domino.{name}")

	# Names `from .core import *` used to bring along (Element, Page, PageStore, Markup, ...)
	from . import _core
	if not name.startswith("_") and hasattr(_core, name):
		_warnings.warn(
			f"domino.{name} isn't part of Domino's API any more; import it from where it's defined",
			DeprecationWarning, stacklevel=2
		)
		return getattr(_core, name)

	raise AttributeError(f"module 'domino' has no attribute {name!r}")


def __dir__():

	return sorted(__all__ + ["accounts", "bootstrap", "forms", "mail", "mongo", "tags", "testing"])
