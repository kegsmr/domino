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
