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