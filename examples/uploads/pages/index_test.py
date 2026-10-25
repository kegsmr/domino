# Tests for pages/index.py: `page` is that page, open in a simulated browser. Run with `pytest`
import base64


# A 1x1 PNG
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def test_uploaded_photos_are_shown(page):

	page.upload("input[name=photos]", ("one.png", PNG), ("two.png", PNG))
	page.click("button", text="Upload")

	images = page.find_all("ul img")
	assert len(images) == 2
	assert "2 image(s)" in page.text()
	# The form was handled, so its file input is empty again
	assert page.find("input[name=photos]").files is None

	# The thumbnails are served back with the type the server checked
	response = page.client.get(images[0].attrs["src"])
	assert response.data == PNG
	assert response.mimetype == "image/png"


def test_files_that_arent_images_are_refused(page):

	page.upload("input[name=photos]", ("notes.png", b"not really a picture", "image/png"))
	page.click("button", text="Upload")

	assert page.find_all("ul img") == []
	assert "Only PNG, JPEG, GIF and WebP" in page.text(".message")


def test_the_avatar_uploads_as_soon_as_it_is_picked(page):

	page.upload("input[name=avatar]", ("me.png", PNG))

	assert page.find(".avatar img").attrs["src"].startswith("/images/")
