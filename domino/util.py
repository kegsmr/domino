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
