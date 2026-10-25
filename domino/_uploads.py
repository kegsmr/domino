"""File uploads: files go up in their own multipart POST, not with the event.

The browser POSTs the files an event carries to /_domino/upload and gets back one opaque token
per file; the event (over the WebSocket or HTTP) then sends the tokens, and the server swaps them
for the files, as `event.files`. A token belongs to the page that uploaded it, works once, and
expires. Files are spooled to temporary files (in memory only while small) and deleted once the
event has been handled, or when they expire unclaimed.
"""

import os
import secrets
import threading
import time
from contextlib import contextmanager

from werkzeug.datastructures import FileStorage, MultiDict


class UploadedFile(FileStorage):
	"""An uploaded file, as werkzeug's FileStorage: `read()`, `save(path)`, `stream`, `filename`,
	`content_type`, plus `size` in bytes. The filename and content type are what the browser
	said; don't trust them (use werkzeug.utils.secure_filename, check the content yourself)."""


	def __init__(self, storage):

		super().__init__(storage.stream, storage.filename, storage.name, storage.content_type, None, storage.headers)

		self.stream.seek(0, os.SEEK_END)
		self.size = self.stream.tell()
		self.stream.seek(0)


	def __repr__(self):

		return f"<UploadedFile {self.filename!r} ({self.content_type}, {self.size} bytes)>"


class Uploads:
	"""Files uploaded for events that haven't been handled yet: token -> (page id, time, file)."""


	def __init__(self, config):

		self.config = config  # the app's, for DOMINO_UPLOAD_TTL
		self.files = {}  # oldest first (dicts keep their order), so pruning stops early
		self.lock = threading.Lock()


	def add(self, page_id, files):
		"""Keep `files` (a MultiDict of FileStorage) for `page_id`; returns {name: [token, ...]}."""

		self.prune()
		tokens = {}
		now = time.monotonic()

		with self.lock:
			for name, storage in files.items(multi=True):
				token = secrets.token_urlsafe(24)
				self.files[token] = (page_id, now, UploadedFile(storage))
				tokens.setdefault(name, []).append(token)

			# Unclaimed uploads can't pile up (on disk) until they expire: a page keeps at most two
			# uploads' worth, and all pages together DOMINO_MAX_PENDING_UPLOADS_MB; beyond that the
			# oldest go (an upload is normally claimed by its event a moment after it's made)
			upload = self.config["DOMINO_MAX_UPLOAD_MB"] * 1024 * 1024
			pending = self.config.get("DOMINO_MAX_PENDING_UPLOADS_MB", 256) * 1024 * 1024
			expired = self.evict(page_id, 2 * upload) + self.evict(None, max(pending, upload))

		for file in expired:
			file.close()

		return tokens


	def evict(self, page_id, limit):
		"""Take the oldest files out (of `page_id`'s, or anyone's for None) until those left add up
		to `limit` bytes; returns them. Call with self.lock held."""

		entries = [(token, entry) for token, entry in self.files.items() if page_id is None or entry[0] == page_id]
		total = sum(entry[2].size for _, entry in entries)
		evicted = []

		for token, entry in entries:
			if total <= limit:
				break
			del self.files[token]
			total -= entry[2].size
			evicted.append(entry[2])

		return evicted


	@contextmanager
	def claim(self, page, data):
		"""The files an event's `data` names by token ({"files": {name: [token, ...]}}), as a
		MultiDict, or None if any token is unknown, expired or another page's. They're taken out
		of the store (a token works once) and closed, deleting them, when the block ends."""

		self.prune()
		requested = data.get("files") if isinstance(data, dict) else None
		files = MultiDict()
		valid = True

		if isinstance(requested, dict):
			with self.lock:
				for name, tokens in requested.items():
					for token in tokens if isinstance(tokens, list) else [tokens]:
						entry = self.files.get(token) if isinstance(token, str) else None
						# Another page's token stays where it is; it isn't this page's to use up
						if entry is None or entry[0] != page.id:
							valid = False
							continue
						del self.files[token]
						files.add(name, entry[2])

		try:
			yield files if valid else None
		finally:
			for _, file in files.items(multi=True):
				file.close()


	def prune(self):
		"""Delete files that weren't claimed in time."""

		cutoff = time.monotonic() - self.config["DOMINO_UPLOAD_TTL"]
		expired = []

		with self.lock:
			for token, (_, created, file) in list(self.files.items()):
				if created >= cutoff:
					break
				del self.files[token]
				expired.append(file)

		for file in expired:
			file.close()


	def __len__(self):

		return len(self.files)


def parse(environ, max_bytes):
	"""The files of a multipart request, as a MultiDict of FileStorage. Raises werkzeug's
	RequestEntityTooLarge past `max_bytes`. Parsed here rather than through `request.files`,
	which Flask closes when the request ends; these must outlive it until the event comes."""

	from werkzeug.formparser import parse_form_data

	_, _, files = parse_form_data(environ, max_content_length=max_bytes)

	return files
