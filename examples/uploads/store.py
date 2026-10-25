"""Uploaded images, kept in this process's memory (a real app would use disk or object storage)."""

import secrets
from collections import OrderedDict


# The newest images, by id: (bytes, content type)
images = OrderedDict()
MAX_IMAGES = 50

# The browser's content type and the input's accept="image/*" can't be trusted, so the
# file's first bytes decide (and SVG, which can hold scripts, isn't accepted)
SIGNATURES = [
	(b"\x89PNG\r\n\x1a\n", "image/png"),
	(b"\xff\xd8\xff", "image/jpeg"),
	(b"GIF87a", "image/gif"),
	(b"GIF89a", "image/gif"),
]


def image_type(data):

	for signature, content_type in SIGNATURES:
		if data.startswith(signature):
			return content_type
	if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
		return "image/webp"

	return None


def save(file):
	"""Keep an uploaded file if it's an image; returns its id, or None."""

	data = file.read()
	content_type = image_type(data)
	if content_type is None:
		return None

	id = secrets.token_hex(8)
	images[id] = (data, content_type)
	while len(images) > MAX_IMAGES:
		images.popitem(last=False)

	return id
