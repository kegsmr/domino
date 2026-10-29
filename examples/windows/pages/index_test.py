def test_settings_opens_in_a_window_that_changes_this_page(page):

	assert page.text("p") == "Theme: light"
	page.click("button", text="Settings")

	settings = page.window("Settings")
	assert settings.text("title") == "Settings"
	assert settings.text("p") == "Section: general"

	settings.select("select", "dark")
	page.sync()
	assert page.text("p") == "Theme: dark"

	settings.click("button", text="Done")
	assert settings.closed


def test_a_window_opened_with_a_value(page):

	page.click("button", text="Audio settings")

	assert page.window("Settings").text("p") == "Section: audio"
