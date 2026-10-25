# The docs site needs Markdown and Pygments (docs/requirements.txt), which Domino itself doesn't;
# without them its tests are left out rather than failing
try:
	import markdown  # noqa: F401
	import pygments  # noqa: F401
except ImportError:
	collect_ignore_glob = ["*"]
