import sys

from domino import template

from components.counter import Counter

Todo = None
if sys.version_info >= (3, 14):
	from components.todo import Todo


# This file is the page at /. home.html is found by name anywhere in the app's folder,
# and a template returned from a page is the whole page
def page():

	return template("home.html", title="Templates", Counter=Counter, Todo=Todo)
