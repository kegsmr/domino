import inspect
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlsplit


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


def is_local_url(url):
	"""Whether `url` is a path on this site ("/notes?page=2"), not a link to another site
	("//evil.com", "https://evil.com", "/\\evil.com", which browsers treat as "//evil.com")."""

	if not isinstance(url, str) or not url.startswith("/") or url.startswith("//"):
		return False

	# Browsers read backslashes as slashes and drop tabs and newlines, so "/\t/evil.com" is "//evil.com"
	if "\\" in url or any(ord(character) < 32 or ord(character) == 127 for character in url):
		return False

	parts = urlsplit(url)

	return not parts.scheme and not parts.netloc


def urlopen(url, timeout=60):
	"""urllib.request.urlopen for Domino's downloads (MongoDB, Tailwind CSS, ...), which also trusts
	certifi's certificates when the system's don't verify the site: Python from python.org on
	macOS has none until its "Install Certificates" script is run, and Windows may lack one."""

	try:
		return urllib.request.urlopen(url, timeout=timeout)
	except urllib.error.URLError as error:
		if not isinstance(error.reason, ssl.SSLCertVerificationError):
			raise
		try:
			import certifi
		except ImportError:
			raise error from None
		context = ssl.create_default_context(cafile=certifi.where())
		return urllib.request.urlopen(url, timeout=timeout, context=context)


def download_problem(error):
	"""Why a download failed, in words, with what to do about a certificate problem."""

	reason = getattr(error, "reason", None) or error
	if isinstance(reason, ssl.SSLCertVerificationError):
		return (
			f"{reason}. Python can't check the site's certificate: with Python from python.org on macOS, "
			"run \"Install Certificates.command\" in its Applications folder (or pip install --upgrade certifi)"
		)

	return str(reason)

