import sys

from domino import template

from components.counter import Counter

Todo = None
if sys.version_info >= (3, 14):
	from components.todo import Todo


# The page at /jinja: jinja_home.html is a Jinja template ({% %} blocks), found by name anywhere
# in the app's folder. A template returned from a page is the whole page
def page():

	return template("jinja_home.html", title="Jinja templates", Counter=Counter, Todo=Todo)
