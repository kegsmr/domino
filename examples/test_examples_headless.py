"""Testing a Domino app without a browser: `app.test_page()`.

Run from the repository root:

	python -m pytest examples/test_examples_headless.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import counter
import search
import todo


def test_counter():

	page = counter.app.test_page("/")

	page.click("button", text="Increment")
	page.click("button", text="Increment")
	page.click("button", text="Decrement")

	assert page.text("p") == "Current Count: 1"


def test_todo():

	page = todo.app.test_page("/")

	page.fill("input[name=text]", "Buy milk")
	page.click("button", text="Add")
	page.fill("input[name=text]", "Walk the dog")
	page.click("button", text="Add")

	assert [item.text for item in page.find_all("li")] == ["Buy milk", "Walk the dog"]
	assert page.text("p") == "2 item(s)"
	assert page.value("input[name=text]") == ""

	# Ticking an item's checkbox removes it
	page.click("li input[type=checkbox]")

	assert [item.text for item in page.find_all("li")] == ["Walk the dog"]


def test_search():

	page = search.app.test_page("/")

	page.type("input[type=search]", "ru")

	assert [item.text for item in page.find_all("li")] == ["Ruby", "Rust"]
	assert page.text("p") == "2 match(es), 1 request(s) sent"
