# Tests for pages/index.py: `page` is that page, open in a simulated browser. Run with `pytest`.
# It doesn't run JavaScript or the browser's Python, so these check the HTML the server renders
# for the client components (what shows before Python has loaded) and the server components;
# tests/test_client_browser.py runs the client components in a real browser.

import json


def test_the_board_is_rendered_by_the_server(page):

	assert len(page.find_all(".Life .board span")) == 20 * 20
	assert len(page.find_all(".Life .board span.on")) == 16
	assert page.text(".Life .status") == "Generation 0 · 16 alive"
	assert page.find(".Life button", text="Start")


def test_client_components_carry_their_state_for_the_browser(page):

	life = page.find(".Life")
	state = json.loads(life.attrs["data-domino-state"])

	assert life.attrs["data-domino-client"].startswith("components.life@")
	assert state["state"]["running"] is False
	assert sum(state["state"]["cells"]) == 16
	# The server's handler for "Save to server" (self.emit("save", ...)) is bound on it
	assert life.attrs["data-event-id"].endswith("-save")
	# Its own handlers run in the browser, so the server binds none of them
	assert "data-event-id" not in page.find(".Life button", text="Start").attrs
	assert page.find(".Life button", text="Start").attrs["data-domino-on"].startswith("click:")


def test_the_server_component_still_runs_on_the_server(page):

	assert page.text(".ServerTextStats dd") == "55"

	page.type(".ServerTextStats textarea", "One two three. Four!")

	assert page.text(".ServerTextStats dl") == "Characters 20 Words 4 Sentences 2 Longest word three. Reading time 1 s"


def test_nothing_saved_yet(page):

	assert "Nothing yet" in page.text(".Patterns")
