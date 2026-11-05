"""What a user sees, measured in headless Chromium with Playwright.

Times come from the page's own clock: an interaction starts at the timeStamp of its first input
event (pointerdown, seen by a capture listener on window, before any framework's listener),
and ends when a MutationObserver sees the DOM show the expected change: when the DOM is
updated, before paint. Across tabs, times are made absolute with performance.timeOrigin.
"""

import asyncio
import base64
import gzip
import statistics


# Installed in every page before its own scripts run
INIT = """
(() => {
  const bench = window.__bench = { armed: false, t0: undefined, done: undefined };
  for (const type of ['pointerdown', 'mousedown', 'keydown', 'click']) {
    window.addEventListener(type, (event) => {
      if (bench.armed && bench.t0 === undefined) bench.t0 = event.timeStamp;
    }, { capture: true });
  }
  // Calls done() with the time the DOM first satisfies check()
  bench.watch = (check, done) => {
    const observer = new MutationObserver(() => {
      if (check()) { observer.disconnect(); done(performance.now()); }
    });
    observer.observe(document, { subtree: true, childList: true, characterData: true, attributes: true });
    return observer;
  };
  bench.text = (selector) => { const element = document.querySelector(selector); return element ? element.textContent : null; };
  // Resolves once the DOM hasn't changed for `ms` (late answers from the server have landed)
  bench.quiet = (ms, most = 10000) => new Promise((resolve) => {
    const started = performance.now();
    let timer;
    const observer = new MutationObserver(() => { clearTimeout(timer); timer = setTimeout(finish, ms); });
    const finish = () => { observer.disconnect(); resolve(performance.now() - started); };
    observer.observe(document, { subtree: true, childList: true, characterData: true, attributes: true });
    timer = setTimeout(finish, ms);
    setTimeout(finish, most);
  });
  bench.arm = (check) => {
    bench.armed = true; bench.t0 = undefined; bench.done = undefined;
    bench.watch(check, (time) => { bench.done = time; });
  };
})();
"""

# Clicks until the click works: the time from navigation to the first DOM update a click causes
FIRST_INTERACTION = """
async ([clickSelector, index, watchSelector, timeout]) => {
  const bench = window.__bench;
  const started = performance.now();
  let initial = null, changed = null, observer = null;
  while (performance.now() - started < timeout) {
    const target = document.querySelectorAll(clickSelector)[index];
    const watched = bench.text(watchSelector);
    if (target && watched !== null) {
      if (initial === null) {
        initial = watched;
        observer = bench.watch(() => bench.text(watchSelector) !== null && bench.text(watchSelector) !== initial,
          (time) => { changed = time; });
      }
      target.click();
      const until = performance.now() + 100;
      while (changed === null && performance.now() < until) await new Promise((resolve) => setTimeout(resolve, 5));
      if (changed !== null) break;
    } else {
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
  }
  if (observer) observer.disconnect();
  const paint = performance.getEntriesByName('first-contentful-paint')[0];
  return { interactive: changed, fcp: paint ? paint.startTime : null };
}
"""


def percentile(values, p):

	values = sorted(values)
	if not values:
		return None
	k = (len(values) - 1) * p / 100
	low = int(k)
	high = min(low + 1, len(values) - 1)

	return values[low] + (values[high] - values[low]) * (k - low)


def summary(values):

	values = [value for value in values if value is not None]
	if not values:
		return None

	return {"median": statistics.median(values), "p95": percentile(values, 95), "min": min(values), "max": max(values),
		"n": len(values), "samples": [round(value, 2) for value in values]}


def merge(summaries):
	"""One summary of the samples of several (from repeated rounds)."""

	summaries = [item for item in summaries if item]
	if not summaries:
		return None

	return summary([value for item in summaries for value in item["samples"]])


async def new_page(browser):

	context = await browser.new_context()
	await context.add_init_script(INIT)
	page = await context.new_page()

	return context, page


class Traffic:
	"""Bytes a page loads: HTTP as transferred (headers included, compressed if the server
	compressed), HTTP bodies decoded and as gzip -6 would make them (the same compression for
	everyone, whatever each server does), and WebSocket payloads as the page receives them
	(after any permessage-deflate is undone: CDP doesn't show frames' compressed size)."""


	def __init__(self):

		self.transferred = 0
		self.decoded = 0
		self.requests = 0
		self.ws_received = 0
		self.ws_sent = 0
		self.encodings = {}
		self.finished = []


	def total(self):

		return self.transferred + self.ws_received + self.ws_sent


	async def attach(self, context, page):

		cdp = self.cdp = await context.new_cdp_session(page)
		urls = {}

		def response(event):
			headers = {key.lower(): value for key, value in event["response"]["headers"].items()}
			urls[event["requestId"]] = (event["response"]["url"], headers.get("content-encoding", "identity"))

		def data(event):
			self.decoded += event["dataLength"]

		def finished(event):
			self.transferred += event["encodedDataLength"]
			self.requests += 1
			self.finished.append(event["requestId"])
			url, encoding = urls.get(event["requestId"], ("?", "?"))
			self.encodings[url.split("?")[0].rsplit("/", 1)[-1] or "/"] = encoding

		def received(event):
			self.ws_received += len(event["response"]["payloadData"].encode())

		def sent(event):
			self.ws_sent += len(event["response"]["payloadData"].encode())

		cdp.on("Network.responseReceived", response)
		cdp.on("Network.dataReceived", data)
		cdp.on("Network.loadingFinished", finished)
		cdp.on("Network.webSocketFrameReceived", received)
		cdp.on("Network.webSocketFrameSent", sent)
		await cdp.send("Network.enable")
		await cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})

		return cdp


	async def gzipped(self):
		"""The bodies loaded so far, each compressed with gzip -6."""

		total = 0
		for request_id in self.finished:
			try:
				body = await self.cdp.send("Network.getResponseBody", {"requestId": request_id})
			except Exception:
				continue
			data = base64.b64decode(body["body"]) if body["base64Encoded"] else body["body"].encode()
			total += len(gzip.compress(data, 6))

		return total


async def page_weight(browser, url, settle=2.0):
	"""What a cold load of `url` brings over the network, until it has settled."""

	context, page = await new_page(browser)
	traffic = Traffic()
	try:
		await traffic.attach(context, page)
		await page.goto(url, wait_until="load")
		# Late requests (fonts, lazy chunks) and the socket's first messages (some frameworks send
		# the page's data over it)
		await asyncio.sleep(settle)
		return {
			"transferred_bytes": traffic.transferred,
			"decoded_bytes": traffic.decoded,
			"gzip_bytes": await traffic.gzipped(),
			"requests": traffic.requests,
			"ws_received_bytes": traffic.ws_received,
			"encodings": traffic.encodings,
		}
	finally:
		await context.close()


async def first_load(browser, url, interaction):
	"""A cold load of `url`: first contentful paint, and the first click that works (the time
	from navigation to the DOM update it causes), clicking every 100 ms until one does."""

	context, page = await new_page(browser)
	try:
		await page.goto(url, wait_until="commit")
		result = await page.evaluate(FIRST_INTERACTION, [interaction["click"], interaction.get("index", 0), interaction["watch"], 30000])
		if result["fcp"] is None:
			await asyncio.sleep(0.5)
			result["fcp"] = await page.evaluate("(performance.getEntriesByName('first-contentful-paint')[0] || {}).startTime ?? null")
		return {"fcp_ms": result["fcp"], "interactive_ms": result["interactive"]}
	finally:
		await context.close()


async def first_paint(browser, url):

	context, page = await new_page(browser)
	try:
		await page.goto(url, wait_until="load")
		await asyncio.sleep(0.5)
		return {"fcp_ms": await page.evaluate("(performance.getEntriesByName('first-contentful-paint')[0] || {}).startTime ?? null"),
			"interactive_ms": None}
	finally:
		await context.close()


async def page_load(browser, url, check=None, traffic=None):
	"""Open `url` in a fresh context; with `check`, until it has worked once (FIRST_INTERACTION).
	A `traffic` (Traffic) counts the page's bytes."""

	context, page = await new_page(browser)
	if traffic:
		await traffic.attach(context, page)
	await page.goto(url, wait_until="commit")
	if check:
		result = await page.evaluate(FIRST_INTERACTION, [check["click"], check.get("index", 0), check["watch"], 60000])
		if result["interactive"] is None:
			raise RuntimeError(f"{url}: no interaction worked")

	return context, page


async def interact(page, action, check, timeout=30000):
	"""Run `action` (an async function doing real input), and return the ms from its first input
	event until the DOM satisfies `check` (a JS expression)."""

	await page.evaluate("(check) => window.__bench.arm(new Function('return (' + check + ')'))", check)
	await action()
	await page.wait_for_function("window.__bench.done !== undefined", timeout=timeout, polling="raf")
	latency = await page.evaluate("window.__bench.done - window.__bench.t0")
	await page.evaluate("window.__bench.armed = false")

	return latency
