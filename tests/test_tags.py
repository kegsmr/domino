import ast
from pathlib import Path

import domino.tags as t
from domino._core import Element


def test_every_tag_renders_its_own_name():

	for name in t.TAGS:
		tag = getattr(t, name)
		assert tag.__name__ == name
		assert issubclass(tag, Element)
		assert tag()._render(indent="").startswith(f"<{name}")


def test_stub_matches_tags():

	stub = ast.parse((Path(t.__file__).parent / "tags.pyi").read_text())
	stubbed = [node.name for node in stub.body if isinstance(node, ast.ClassDef)]

	assert stubbed == t.TAGS + ["Component"]


def test_subclassing_a_tag():

	class Card(t.div):
		pass

	html = Card() ["hi"]._render(indent="")

	assert html.startswith('<div class="Card"')
