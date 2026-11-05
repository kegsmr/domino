"""Patches: a re-rendered component sent as what changed since the last HTML the socket sent for it.

Components render one element per line, so a change usually touches a few lines. diff() trims the
lines both versions start and end with, then copies whatever runs of old lines it finds in the
middle (a moved or shifted block costs a few bytes) and sends only new text. The patch is a list
of ops, each either [start, count] (lines start..start+count-1 of the old HTML) or a string (new
lines, joined with "\\n"); joining the pieces with "\\n" gives the new HTML. core.js keeps the last
HTML per component as the server does (see Patcher), so it can apply them.
"""

import threading
from bisect import bisect_left
from collections import OrderedDict


# Smaller HTML is sent whole: a patch would save little, and isn't worth keeping a base for
MIN_SIZE = 1024

# HTML kept per socket as bases for patches; the least recently sent goes first beyond it
LIMIT = 512 * 1024

# About what a copy costs in JSON, "[1234,56]," so shorter runs of lines are sent as text
COPY_COST = 10

# A patch is sent only when it's at most this much of the HTML
SMALLER = 0.8


def diff(old, new):
	"""The ops that turn `old` into `new`, or None if sending `new` whole is about as small."""

	a = old.split("\n")
	b = new.split("\n")

	prefix = common_prefix(a, b)
	suffix = common_suffix(a, b, min(len(a), len(b)) - prefix)
	a_end = len(a) - suffix
	b_end = len(b) - suffix

	ops = []
	if prefix:
		ops.append([0, prefix])
	if prefix < b_end:
		middle(a, b, prefix, a_end, prefix, b_end, ops)
	if suffix:
		copy(ops, a_end, suffix)

	size = sum(len(op) if isinstance(op, str) else COPY_COST for op in ops)
	if size > len(new) * SMALLER:
		return None

	return ops


def common_prefix(a, b):
	"""How many items lists `a` and `b` start with in common. Compares slices, so the work
	is done in C: a binary search for where they part."""

	low, high = 0, min(len(a), len(b))
	while low < high:
		mid = (low + high + 1) // 2
		if a[low:mid] == b[low:mid]:
			low = mid
		else:
			high = mid - 1

	return low


def common_suffix(a, b, most):
	"""How many items (at most `most`) lists `a` and `b` end with in common."""

	low, high = 0, most
	while low < high:
		mid = (low + high + 1) // 2
		if a[len(a) - mid:len(a) - low] == b[len(b) - mid:len(b) - low]:
			low = mid
		else:
			high = mid - 1

	return low


def middle(a, b, a_start, a_end, b_start, b_end, ops):
	"""Ops for lines b[b_start:b_end], copying runs of a[a_start:a_end] where they're found."""

	index = {}
	for i in range(a_start, a_end):
		index.setdefault(a[i], []).append(i)

	text = []
	expect = a_start  # where the old lines would continue, preferred when a line repeats
	j = b_start
	while j < b_end:
		positions = index.get(b[j])
		if positions:
			k = bisect_left(positions, expect)
			i = positions[k] if k < len(positions) else positions[0]
			count = 1
			size = len(b[j])
			while j + count < b_end and i + count < a_end and a[i + count] == b[j + count]:
				size += len(b[j + count]) + 1
				count += 1
			if size > COPY_COST:
				if text:
					ops.append("\n".join(text))
					text = []
				copy(ops, i, count)
				expect = i + count
				j += count
				continue
		text.append(b[j])
		j += 1

	if text:
		ops.append("\n".join(text))


def copy(ops, start, count):

	last = ops[-1] if ops else None
	if isinstance(last, list) and last[0] + last[1] == start:
		last[1] += count
	else:
		ops.append([start, count])


def apply(old, ops):
	"""The HTML a patch makes of `old` (what core.js does; for tests and tools)."""

	lines = old.split("\n")
	pieces = []
	for op in ops:
		if isinstance(op, str):
			pieces.append(op)
		else:
			pieces.extend(lines[op[0]:op[0] + op[1]])

	return "\n".join(pieces)


# A refresh() renders once and sends the same HTML to every page showing the component, so
# their sockets diff the same two strings; the last few diffs are kept, by identity
_diffs = OrderedDict()
_diffs_lock = threading.Lock()
_DIFFS_KEPT = 8


def cached_diff(old, new):

	key = (id(old), id(new))
	with _diffs_lock:
		found = _diffs.get(key)
	# The entry holds both strings, so their ids can't have been reused
	if found is not None and found[0] is old and found[1] is new:
		return found[2]

	ops = diff(old, new)

	with _diffs_lock:
		_diffs[key] = (old, new, ops)
		while len(_diffs) > _DIFFS_KEPT:
			_diffs.popitem(last=False)

	return ops


class Patcher:
	"""What one socket last sent of each component, to send the next as a patch against it.
	Messages must be encoded in the order they're sent: the browser keeps the last HTML it
	received per component, so the two agree on what a patch starts from."""


	def __init__(self, limit=LIMIT):

		self.limit = limit
		self.sent = OrderedDict()  # component id -> (version, html), least recently sent first
		self.size = 0  # characters of HTML in self.sent


	def encode(self, message):
		"""`message` (a result or update), with "patch" and "base" (the version it starts from)
		in place of "html" when that's smaller."""

		html = message.get("html")
		key = message.get("id")
		if not html or not key or "version" not in message:
			return message

		previous = self.sent.pop(key, None)
		if previous is not None:
			self.size -= len(previous[1])

		if len(html) < MIN_SIZE:
			return message

		self.sent[key] = (message["version"], html)
		self.size += len(html)
		while self.size > self.limit:
			_, (_, evicted) = self.sent.popitem(last=False)
			self.size -= len(evicted)

		if previous is None:
			return message

		ops = cached_diff(previous[1], html)
		if ops is None:
			return message

		patched = dict(message, patch=ops, base=previous[0])
		del patched["html"]

		return patched


	def resend(self, key):
		"""The last HTML sent for a component, whole, for a browser that lost track of it (or
		None if it's no longer kept, in which case the next update is sent whole anyway)."""

		previous = self.sent.get(key)
		if previous is None:
			return None

		return {"type": "update", "id": key, "html": previous[1], "version": previous[0]}


	def clear(self):

		self.sent.clear()
		self.size = 0
