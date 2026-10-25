import inspect


# Class attributes per class, computed once: walking the hierarchy for every element on
# every render was the biggest cost of rendering
_class_attributes = {}


def get_class_attributes(obj):
    """Returns a dictionary of all class attributes, including inherited ones, 
    excluding methods, instance attributes, and dunder attributes."""
    
    cls = obj if isinstance(obj, type) else obj.__class__

    cached = _class_attributes.get(cls)
    if cached is None:
        # Retrieve all attributes in the class hierarchy (including inherited ones)
        cached = {}
        for base in reversed(cls.__mro__):  # Iterate over base classes (from top to bottom)
            for k, v in base.__dict__.items():
                # Exclude dunders, methods and descriptors (properties, State attributes)
                if not k.startswith("__") and not callable(v) and not hasattr(type(v), "__get__"):
                    cached[k] = v  # Overwrite if a subclass redefines the attribute
        _class_attributes[cls] = cached

    # Callers change the result, so hand out a copy
    return dict(cached)


def accepts_argument(func):
	"""Returns True if `func` can be called with one positional argument."""

	try:
		parameters = inspect.signature(func).parameters.values()
	except (TypeError, ValueError):
		return False

	return any(
		parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD, parameter.VAR_POSITIONAL)
		for parameter in parameters
	)


def css_class_name(cls):
	"""The CSS class a Python class renders as: underscores become hyphens (col_6 -> col-6)."""

	return cls.__name__.replace("_", "-")
