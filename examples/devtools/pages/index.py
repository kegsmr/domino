import domino.tags as t

from components.counter import Counter
from components.crash import Crash
from components.todo import TodoList


# This file is the page at /
def page():

	return t.div() [
		t.h1() [
			"Developer tools"
		],
		t.p() [
			"In debug mode (",
			t.code() ["python examples/devtools/app.py"],
			" or ",
			t.code() ["domino run examples/devtools"],
			"), press ",
			t.code() ["Alt+Shift+D"],
			" or run ",
			t.code() ["Domino.inspect()"],
			" in the browser console, then hover a component and click it: the panel shows its State "
			"(kept up to date as you click), its events and whether they're instant, what it subscribed "
			"to and its parents. Its Events tab lists this page's events with their timings."
		],
		Counter(),
		TodoList(),
		Crash()
	]
