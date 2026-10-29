"""Gzip for responses: pages, /_domino/core, event results over HTTP and Server-Sent Event streams.

Pages and the script are mostly repeated markup, so gzip shrinks them several times over (a
1,000-row list page goes from 77 KB to 3 KB, /_domino/core from 58 KB to 16 KB). Only browsers that send Accept-Encoding:
gzip get it, and only for text bigger than MIN_SIZE. Files sent with send_file() (direct
passthrough) are left to a proxy or CDN, and the WebSocket has its own per-message deflate.
{"domino": {"compression": false}} turns it off, e.g. when a proxy in front compresses already.
"""

import gzip
import zlib


# Smaller bodies would gain a few hundred bytes at most
MIN_SIZE = 1024

# Fast, and within a few percent of level 9 for HTML
LEVEL = 6

# Streams keep a compressor each for as long as the tab is open, so a smaller window and
# memory level hold about a fifth of the defaults' 256 KB (16 + 13: gzip, with an 8 KB window)
STREAM_WBITS = 16 + 13
STREAM_MEMLEVEL = 5

COMPRESSIBLE = ("application/javascript", "application/json", "application/xml", "image/svg+xml")


def accepts_gzip(header):
	"""Whether an Accept-Encoding header allows gzip (by name, or by "*"), honoring q=0."""

	anything = None
	for part in (header or "").split(","):
		name, *params = part.split(";")
		name = name.strip().lower()
		quality = 1.0
		for param in params:
			key, _, value = param.partition("=")
			if key.strip().lower() == "q":
				try:
					quality = float(value)
				except ValueError:
					quality = 0.0
		if name in ("gzip", "x-gzip"):
			return quality > 0
		if name == "*":
			anything = quality > 0

	return bool(anything)


def compressible(mimetype):

	mimetype = (mimetype or "").lower()
	if mimetype == "text/event-stream":
		return False

	return mimetype.startswith("text/") or mimetype in COMPRESSIBLE or mimetype.endswith(("+json", "+xml"))


def compress_response(response, accept_encoding):
	"""Gzip a finished Flask response in place if it's worth it and the browser accepts it."""

	# Streamed bodies (Server-Sent Events, send_file) can't be read whole here
	if response.direct_passthrough or response.is_streamed or not compressible(response.mimetype):
		return response

	# Whether it's compressed depends on the request, so caches must keep both versions
	response.vary.add("Accept-Encoding")

	if response.status_code != 200 or "Content-Encoding" in response.headers:
		return response
	if not accepts_gzip(accept_encoding):
		return response

	body = response.get_data()
	if len(body) < MIN_SIZE:
		return response

	set_gzip(response, compress(body))

	return response


def compress(data):

	# mtime=0 so the same body always gives the same bytes
	return gzip.compress(data, LEVEL, mtime=0)


def set_gzip(response, data):

	response.set_data(data)
	response.headers["Content-Encoding"] = "gzip"
	# Byte ranges would count the uncompressed body
	response.headers.pop("Accept-Ranges", None)
	# The same entity tag would claim the compressed bytes are the uncompressed ones
	etag, weak = response.get_etag()
	if etag and not weak:
		response.set_etag(etag, weak=True)


class GzipStream:
	"""Gzips a stream chunk by chunk, flushing each so the browser sees it at once."""


	def __init__(self):

		self.compressor = zlib.compressobj(LEVEL, zlib.DEFLATED, STREAM_WBITS, STREAM_MEMLEVEL)


	def chunk(self, data):

		return self.compressor.compress(data) + self.compressor.flush(zlib.Z_SYNC_FLUSH)


	def end(self):

		return self.compressor.flush()
