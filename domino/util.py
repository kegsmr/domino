def get_enclosing_class(cls):
    
    if '.' in cls.__qualname__:
        
        outer_class_name = cls.__qualname__.split('.')[0]
        module = __import__(cls.__module__)
        
        return getattr(module, outer_class_name)
    
    return None


def get_custom_attributes(cls):
	
	import inspect

	# Filter out methods and classes, return the rest as a dictionary of key-value pairs
	return {attr: getattr(cls, attr) for attr in dir(cls) 
			if not attr.startswith("__") and not inspect.isfunction(getattr(cls, attr)) and not inspect.isclass(getattr(cls, attr))}


def get_inner_classes(cls):
    
    return {name: obj for name, obj in cls.__dict__.items() if isinstance(obj, type)}


def get_calling_object():
     
	import inspect

	# Inspect the call stack
	stack = inspect.stack()
	caller_frame = stack[1]  # The frame of the caller
	caller_locals = caller_frame.frame.f_locals

	# Look for 'self' in the caller's local variables
	return caller_locals.get("self", None)


def create_class_stub(name):
    """Dynamically creates a class with the given name and returns it."""
    
    namespace = {}
    
    exec(f"""
class {name}:
    pass
""", namespace)
    
    return namespace[name]


def get_class_attributes(obj):
    """Returns a dictionary of all class attributes, including inherited ones, 
    excluding methods, instance attributes, and dunder attributes."""
    
    cls = obj if isinstance(obj, type) else obj.__class__
    
    # Retrieve all attributes in the class hierarchy (including inherited ones)
    attributes = {}
    for base in reversed(cls.__mro__):  # Iterate over base classes (from top to bottom)
        for k, v in base.__dict__.items():
            if not k.startswith("__") and not callable(v):  # Exclude dunder & methods
                attributes[k] = v  # Overwrite if a subclass redefines the attribute

    return attributes