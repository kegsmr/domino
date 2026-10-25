"""Editors (Pylance, pyright) understand State: self.count is an int, so `self.count += 1` passes."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

COMPONENT = '''
import domino.tags as t
from domino import State


class Counter(t.div):

	count = State(0)
	items = State([])
	name = State("")

	def change(self) -> None:
		self.count += 1
		self.count -= 1
		self.items.append("x")
		self.name = self.name.upper()


reveal_type(Counter().count)
reveal_type(State(0).get())
'''


@pytest.mark.skipif(shutil.which("pyright") is None, reason="pyright isn't installed (pip install pyright)")
def test_editors_know_the_type_of_state(tmp_path):

	(tmp_path / "counter.py").write_text(COMPONENT)

	result = subprocess.run(
		["pyright", "--pythonpath", sys.executable, "counter.py"],
		cwd=tmp_path, capture_output=True, text=True, timeout=300,
		env={**os.environ, "PYTHONPATH": str(ROOT)},
	)

	assert "0 errors" in result.stdout, result.stdout
	assert 'Type of "Counter().count" is "int"' in result.stdout
	assert 'Type of "State(0).get()" is "int"' in result.stdout


POLISHED = '''
from domino import Component, State
import domino.tags as t


class TaskList(Component):

	tasks = []
	page = State(1)
	on_add = None

	def render(self):
		return [
			t.ul [[t.li [task] for task in self.tasks]],
			t.p ["Built with ", t.a(href="/") ["Domino"], "."],
			t.button(on_click=(self.next, 1)) ["Next"],
		]

	def next(self, step: int) -> None:
		self.page += step


TaskList(tasks=[1], class_="x", data_x="1", aria_label="Tasks", on_click=print) ["child"]
reveal_type(t.div ["x"])
reveal_type(TaskList ["x"])
'''


@pytest.mark.skipif(shutil.which("pyright") is None, reason="pyright isn't installed (pip install pyright)")
def test_editors_accept_children_without_a_call_and_component_keywords(tmp_path):

	(tmp_path / "tasks.py").write_text(POLISHED)

	result = subprocess.run(
		["pyright", "--pythonpath", sys.executable, "tasks.py"],
		cwd=tmp_path, capture_output=True, text=True, timeout=300,
		env={**os.environ, "PYTHONPATH": str(ROOT)},
	)

	assert "0 errors" in result.stdout, result.stdout
	# t.div [...] is an element, not a generic type's arguments
	assert 'Type of "t.div["x"]" is "div"' in result.stdout
	assert 'Type of "TaskList["x"]" is "TaskList"' in result.stdout
