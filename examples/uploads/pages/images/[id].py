from flask import Response, abort

from store import images


# This file is the page at /images/<id>: an uploaded image
def page(id):

	if id not in images:
		abort(404)
	data, content_type = images[id]

	# nosniff: the browser uses the type the server checked, never guesses from the bytes
	return Response(data, mimetype=content_type, headers={"X-Content-Type-Options": "nosniff"})
