# Tests for pages/index.py: `page` is that page, open in a simulated browser. Run with `pytest`.
# It doesn't run JavaScript, so these test what the server does; tests/test_browser.py tests
# that clicks show at once in a real browser.

import json


def graph_of(page, selector):
	"""The states a component ships for the browser to show without waiting (see domino/optimistic.py)."""

	component = page.find(selector)
	script = next(child for child in component.children if getattr(child, "tag", None) == "script")
	return json.loads(script.children[0])


def test_tabs_switch(page):

	assert "renders the states" in page.text("[role=tabpanel]")

	page.click("[role=tab]", text="Truth")

	assert "source of truth" in page.text("[role=tabpanel]")
	assert page.find("[role=tab]", text="Truth").attrs["aria-selected"] == "true"


def test_accordion_opens_one_section_at_a_time(page):

	page.click(".Accordion button", text="disagrees")
	assert "Its answer wins" in page.text(".Accordion")

	page.click(".Accordion button", text="qualify")
	assert "Its answer wins" not in page.text(".Accordion")
	assert "plain expressions" in page.text(".Accordion")

	page.click(".Accordion button", text="qualify")
	assert page.find_all(".Accordion p") == []


def test_menu_opens_and_picks(page):

	assert page.find_all(".SortMenu li") == []

	page.click(".SortMenu button", text="Sort")
	page.click("[role=menuitemradio]", text="Oldest")

	assert page.text(".SortMenu") == "Sort: Oldest ▾"


def test_stepper_stays_between_0_and_5(page):

	for _ in range(7):
		page.click("button[aria-label=More]")

	assert page.text("output") == "5"
	assert "disabled" in page.find("button[aria-label=More]").attrs


def test_carousel_wraps_around(page):

	page.click("button[aria-label=Previous]")
	assert page.text("figure") == "Night (4/4)"

	page.click("button[aria-label=Next]")
	assert page.text("figure") == "Dawn (1/4)"


def test_playlist_sorts_and_filters(page):

	page.select(".Playlist select", "year")
	assert page.text(".Playlist li").startswith("♥ So What")

	page.check(".Playlist input[type=checkbox]")
	assert len(page.find_all(".Playlist li")) == 3


def test_todos_add_tick_and_remove(page):

	page.fill(".Todos input[name=text]", "  Water the plants ")
	page.submit(".Todos form")
	assert page.text(".Todos li") == "Water the plants ×"
	assert page.text(".Todos .note") == "1 left"

	page.check(".Todos li input[type=checkbox]")
	assert page.text(".Todos .note") == "0 left"

	page.click(".Todos .remove")
	assert page.find_all(".Todos li") == []


def test_chat_sends(page):

	page.fill(".Chat input[name=name]", "Ada")
	page.fill(".Chat input[name=text]", "Hello")
	page.submit(".Chat form")

	assert page.text(".Chat li") == "Ada Hello"
	assert page.value(".Chat input[name=name]") == "Ada"


def test_every_component_ships_all_its_states(page):

	# How many states each one can be in; each comes with where its events lead
	expected = {".Tabs": 3, ".Accordion": 4, ".SortMenu": 6, ".Stepper": 6, ".Carousel": 4, ".Playlist": 12}

	for selector, count in expected.items():
		graph = graph_of(page, selector)
		assert len(graph["states"]) == count, selector
		assert len(graph["edges"]) == count, selector


def test_collections_ship_the_next_step(page):

	page.fill(".Todos input[name=text]", "Water the plants")
	page.submit(".Todos form")

	graph = graph_of(page, ".Todos")
	edges = graph["edges"][0]
	# Add (with the typed text left for the browser to fill in), tick and remove
	assert len(edges) == 3
	assert any(isinstance(edge, dict) and edge.get("form") == {"text": 0} for edge in edges.values())


def test_states_still_ship_after_a_click(page):

	page.click("button[aria-label=More]")

	# Worked out again from where the server is now: state 0 is the one shown (the browser
	# has its HTML), and "+" leads to 2
	graph = graph_of(page, ".Stepper")
	# Event ids leave out the "event-<component id>-" they all start with
	prefix = f"event-{page.find('.Stepper').attrs['id']}-"
	more = page.find("button[aria-label=More]").attrs["data-event-id"][len(prefix):]
	assert graph["states"][0] is None
	assert len(graph["edges"]) == 6
	assert "2" in graph["states"][graph["edges"][0][more]]
