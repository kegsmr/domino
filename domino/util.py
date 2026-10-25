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