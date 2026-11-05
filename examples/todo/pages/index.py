import domino.tags as t
from domino import Document

from components.todo_list import TodoList


# This file is the page at /
def page():

	return Document(title="Todo") [
		t.h1() [
			"Todo"
		],
		TodoList()
	]
