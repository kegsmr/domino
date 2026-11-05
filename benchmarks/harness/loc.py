"""Lines of app code, as cloc counts them: not blank, not only a comment or a docstring.

Lines from a "--- benchmark hook" comment to the end of a file, and files that exist only for
the load generator (bench_hook.py), aren't counted.
"""

import re

from .frameworks import APPS


# Each framework's files, by app; "shared" is the setup every app of it needs
FILES = {
	"domino": {
		"counter": ["pages/counter.py"],
		"todo": ["pages/todo.py"],
		"chat": ["pages/chat.py", "data.py"],
		"shared": ["app.py"],
	},
	"react": {
		"counter": ["src/Counter.jsx"],
		"todo": ["src/Todo.jsx", "api_todo.py"],
		"chat": ["src/Chat.jsx", "api_chat.py"],
		"shared": ["src/main.jsx", "index.html", "server.py"],
	},
	"htmx": {
		"counter": ["counter.py", "templates/counter.html"],
		"todo": ["todo.py", "templates/todo.html", "templates/todo_item.html", "templates/todo_changed.html"],
		"chat": ["chat.py", "templates/chat.html", "templates/message.html"],
		"shared": ["app.py", "templates/base.html"],
	},
	"nicegui": {
		"counter": ["counter.py"],
		"todo": ["todo.py"],
		"chat": ["chat.py"],
		"shared": ["app.py"],
	},
	"reflex": {
		"counter": ["rxbench/counter.py"],
		"todo": ["rxbench/todo.py"],
		"chat": ["rxbench/chat.py"],
		"shared": ["rxbench/rxbench.py", "rxconfig.py"],
	},
}

COMMENT = {
	".py": re.compile(r"^\s*#"),
	".jsx": re.compile(r"^\s*(//|/\*|\*)"),
	".html": re.compile(r"^\s*(<!--.*-->|\{#.*#\})\s*$"),
}


def count_file(path):

	lines = path.read_text().splitlines()
	comment = COMMENT[path.suffix]
	count = 0
	in_docstring = False
	for line in lines:
		stripped = line.strip()
		if "--- benchmark hook" in line:
			break
		if path.suffix == ".py":
			if in_docstring:
				if stripped.endswith('"""'):
					in_docstring = False
				continue
			if stripped.startswith('"""'):
				if not (len(stripped) > 3 and stripped.endswith('"""')):
					in_docstring = True
				continue
		if not stripped or comment.match(line):
			continue
		# The benchmark hook's import in NiceGUI's app.py
		if "bench_hook" in line:
			continue
		count += 1

	return count


def count():

	results = {}
	for framework, apps in FILES.items():
		row = results[framework] = {}
		for app, files in apps.items():
			row[app] = sum(count_file(APPS / framework / file) for file in files)
		row["total"] = sum(row.values())

	return results


if __name__ == "__main__":
	for framework, row in count().items():
		print(f"{framework:8}", "  ".join(f"{app} {lines}" for app, lines in row.items()))
