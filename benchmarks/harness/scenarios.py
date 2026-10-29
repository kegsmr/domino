"""The measurements, each against a running server (see frameworks.py)."""

import asyncio
import http.client
import itertools
import os
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

import psutil

from .browser import INIT, Traffic, first_load, first_paint, interact, new_page, page_load, page_weight, summary
from .frameworks import free_port


TODO_INPUT = 'input[placeholder="What needs doing?"]'
CHAT_INPUT = 'input[placeholder="Message"]'
tokens = itertools.count()


def token(prefix):

	return f"{prefix}{os.getpid()}x{next(tokens)}"


def counter_check(framework):
	return {"click": "#inc", "watch": "#count"}


def todo_check(framework, index=0):
	return {"click": framework.toggle, "index": index, "watch": "#summary"}


def js(value):
	"""A JS string literal."""

	import json

	return json.dumps(value)


class Proxy:
	"""proxy.py in front of a port, with a round trip that can be changed."""


	def __init__(self, target, port=None):

		self.port = port or free_port()
		self.process = subprocess.Popen([sys.executable, str(Path(__file__).parent / "proxy.py"), str(self.port), str(target)],
			stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
		assert self.process.stdout.readline().strip() == "ready"
		self.url = f"http://127.0.0.1:{self.port}"


	def set(self, rtt):

		self.process.stdin.write(f"{rtt}\n")
		self.process.stdin.flush()
		assert self.process.stdout.readline().startswith("rtt")


	def stop(self):

		self.process.stdin.close()
		try:
			self.process.wait(5)
		except subprocess.TimeoutExpired:
			self.process.kill()
			self.process.wait(5)


class Poster:
	"""POST /bench/chat over one keep-alive connection, as another user of the chat."""


	def __init__(self, port):

		self.connection = http.client.HTTPConnection("127.0.0.1", port, timeout=60)


	def post(self, text):

		for attempt in range(2):
			try:
				self.connection.request("POST", "/bench/chat?text=" + urllib.parse.quote(text), headers={"Content-Length": "0"})
				response = self.connection.getresponse()
				response.read()
				break
			except (http.client.RemoteDisconnected, ConnectionError):
				# The server closed the idle keep-alive connection: open another
				self.connection.close()
				if attempt:
					raise
		assert response.status == 200, response.status


	def close(self):

		self.connection.close()


def idle_cpu_rate(server, seconds=3.0):
	"""CPU seconds per second the server uses doing nothing (timers, keepalives)."""

	started, cpu = time.monotonic(), server.cpu()
	time.sleep(seconds)

	return (server.cpu() - cpu) / (time.monotonic() - started)


# 1. First load ------------------------------------------------------------------------------

async def page_weights(browser, url, runs):
	"""Bytes of a cold load of each app (they barely vary between runs)."""

	results = {}
	for app in ("counter", "todo", "chat"):
		samples = [await page_weight(browser, f"{url}/{app}") for _ in range(runs)]
		results[app] = {key: summary([sample[key] for sample in samples])
			for key in ("transferred_bytes", "decoded_bytes", "gzip_bytes", "ws_received_bytes", "requests")}
		results[app]["encodings"] = samples[-1]["encodings"]

	return results


async def first_loads(browser, framework, url, runs):
	"""First contentful paint, and the first click that works, for cold loads of each app."""

	results = {}
	for app, check in (("counter", counter_check(framework)), ("todo", todo_check(framework)), ("chat", None)):
		samples = []
		for _ in range(runs):
			if check:
				samples.append(await first_load(browser, f"{url}/{app}", check))
			else:
				# Nothing a click changes on its own in the chat
				samples.append(await first_paint(browser, f"{url}/{app}"))
		results[app] = {"fcp_ms": summary([sample["fcp_ms"] for sample in samples]),
			"interactive_ms": summary([sample["interactive_ms"] for sample in samples])}

	return results


# 2. Interaction latency (through the latency proxy) and server CPU per interaction ----------

async def interactions(browser, framework, server, proxy, rtts, clicks, idle_rate):
	"""Click latency for each round trip in `rtts`: the counter (state only the UI needs), and a
	todo list's toggle and add (data the server keeps). Before each click the page is left until
	its DOM has been still for a while, so late answers to the last click can't count for this
	one. At 0 ms, also the server's CPU per interaction (less what it spends idle meanwhile)."""

	results = {}
	for rtt in rtts:
		proxy.set(rtt)
		quiet = int(max(150, rtt * 1.5 + 100))
		row = results[rtt] = {}

		async def measure(page, name, count, prepare, action, check):
			# The page has worked once, but may still be connecting or answering that first click
			await asyncio.sleep(3 * rtt / 1000 + 0.5)
			await page.evaluate("(ms) => window.__bench.quiet(ms)", quiet)
			samples = []
			cpu, started, traffic = server.cpu(), time.monotonic(), traffics[page].total()
			for i in range(count):
				await page.evaluate("(ms) => window.__bench.quiet(ms)", quiet)
				before = await prepare(i)
				samples.append(await interact(page, lambda: action(i), check(before)))
			await page.evaluate("(ms) => window.__bench.quiet(ms)", quiet)
			row[name] = summary(samples)
			if rtt == 0:
				used = server.cpu() - cpu - idle_rate * (time.monotonic() - started)
				row[name + "_cpu_ms"] = max(0.0, used) / count * 1000
				row[name + "_bytes"] = (traffics[page].total() - traffic) / count

		traffics = {}

		async def load(path, check):
			traffic = Traffic()
			context, page = await page_load(browser, proxy.url + path, check, traffic)
			traffics[page] = traffic
			return context, page

		# Counter: UI state only
		context, page = await load("/counter", counter_check(framework))
		try:
			await measure(page, "counter", clicks,
				lambda i: page.text_content("#count"),
				lambda i: page.click("#inc"),
				lambda before: f"(document.querySelector('#count').textContent.trim() === '{int(before.strip()) + 1}')")
		finally:
			await context.close()

		# Todo: toggle an item (server data; the React app updates optimistically, as is usual),
		# then add one (shown once the server has it)
		context, page = await load("/todo", todo_check(framework))
		checkboxes = page.locator(framework.toggle)

		async def fill(i):
			text = token("new item ")
			await page.fill(TODO_INPUT, text)
			return text

		try:
			await measure(page, "toggle", clicks,
				lambda i: page.text_content("#summary"),
				lambda i: checkboxes.nth(framework.checkbox_index + i).click(),
				lambda before: f"(window.__bench.text('#summary') !== {js(before)})")
			await measure(page, "add", max(3, clicks // 2),
				fill,
				lambda i: page.click("#add"),
				lambda text: f"(document.querySelector('#todos').textContent.includes({js(text)}))")
		finally:
			await context.close()

	return results


# 3. Memory per idle connected tab -----------------------------------------------------------

async def open_chat_tabs(browser, url, count, poster, per_context=5, concurrency=8):
	"""`count` tabs showing the chat, `per_context` to a browser context (Chromium allows 6
	HTTP/1.1 connections per host and context, and htmx's event stream holds one per tab), and
	proven live by a message reaching all of them."""

	semaphore = asyncio.Semaphore(concurrency)
	contexts = [await browser.new_context() for _ in range((count + per_context - 1) // per_context)]
	tabs = []

	async def open_one(context):
		async with semaphore:
			page = await context.new_page()
			await page.goto(url + "/chat", wait_until="load", timeout=120000)
			tabs.append((context, page))

	await asyncio.gather(*(open_one(contexts[i // per_context]) for i in range(count)))
	await wait_live(tabs, poster)

	return tabs


async def wait_live(tabs, poster, timeout=120):

	deadline = time.monotonic() + timeout
	while True:
		text = token("ping ")
		await asyncio.to_thread(poster.post, text)
		seen = await asyncio.gather(*(page.wait_for_function(
			f"document.querySelector('#messages') && document.querySelector('#messages').textContent.includes({js(text)})",
			timeout=15000) for _, page in tabs), return_exceptions=True)
		if not any(isinstance(result, Exception) for result in seen):
			return
		# Some tab connected late (or reloaded): try again with a new message
		if time.monotonic() > deadline:
			missing = sum(isinstance(result, Exception) for result in seen)
			raise RuntimeError(f"{missing} of {len(tabs)} tabs never showed the message")


async def close_tabs(tabs):

	await asyncio.gather(*(context.close() for context in {context for context, _ in tabs}), return_exceptions=True)


async def idle_memory(browser, server, counts, per_context=5):

	poster = Poster(server.port)
	try:
		# Warm up: the first page load imports, compiles and caches what every later one shares
		tabs = await open_chat_tabs(browser, server.url, 2, poster)
		await close_tabs(tabs)
		await asyncio.sleep(2)

		results = {}
		for count in counts:
			before = server.memory()
			tabs = await open_chat_tabs(browser, server.url, count, poster, per_context)
			await asyncio.sleep(5)
			after = server.memory()
			results[count] = {"before_mb": before / 1e6, "after_mb": after / 1e6, "per_tab_kb": (after - before) / count / 1e3,
				"browser_mb": browser_rss() / 1e6}
			await close_tabs(tabs)
			await asyncio.sleep(3)
	finally:
		poster.close()

	return results


# 4. Chat fan-out: latency from one tab's Send to every tab, and throughput ------------------

WATCH_ALL = """
([text]) => new Promise((resolve) => {
  const seen = () => { const list = document.querySelector('#messages'); return list && list.textContent.includes(text); };
  if (seen()) return resolve(performance.timeOrigin + performance.now());
  window.__bench.watch(seen, (time) => resolve(performance.timeOrigin + time));
})
"""


async def fanout(browser, server, tab_counts, messages, burst, burst_seconds=20, per_context=5):
	"""For each number of tabs: the latency from a Send click in one tab to the message showing in
	every tab (all of them, the sender's included), and the throughput of a burst of messages
	another user posts back to back (POST /bench/chat, one keep-alive connection, each waiting
	for its answer), until every tab shows the last one. A burst stops early after
	`burst_seconds` of posting, for frameworks that can't keep up."""

	poster = Poster(server.port)
	results = {}
	try:
		for count in tab_counts:
			contexts = []
			for _ in range((count + per_context - 1) // per_context):
				context = await browser.new_context()
				await context.add_init_script(INIT)
				contexts.append(context)
			pages = [await contexts[i // per_context].new_page() for i in range(count)]
			tabs = [(contexts[i // per_context], page) for i, page in enumerate(pages)]
			for i in range(0, count, 10):
				await asyncio.gather(*(page.goto(server.url + "/chat", wait_until="load", timeout=120000) for page in pages[i:i + 10]))
			await wait_live(tabs, poster)
			await asyncio.sleep(1)

			sender = pages[0]
			deliveries, slowest = [], []
			for _ in range(messages):
				text = token("hello ")
				watchers = [asyncio.ensure_future(page.evaluate(WATCH_ALL, [text])) for page in pages]
				await asyncio.sleep(0.05)
				await sender.fill(CHAT_INPUT, text)
				await sender.evaluate("window.__bench.armed = true; window.__bench.t0 = undefined")
				await sender.click("#send")
				arrived = await asyncio.wait_for(asyncio.gather(*watchers), 120)
				sent = await sender.evaluate("performance.timeOrigin + window.__bench.t0")
				latencies = [time - sent for time in arrived]
				deliveries += latencies
				slowest.append(max(latencies))
				await asyncio.sleep(0.3)
			row = results[count] = {"delivery_ms": summary(deliveries), "slowest_tab_ms": summary(slowest)}

			if burst:
				last = token("last ")
				watchers = [asyncio.ensure_future(page.evaluate(WATCH_ALL, [last])) for page in pages]
				await asyncio.sleep(0.2)
				cpu = server.cpu()
				started = time.time()
				posted = 0
				while posted < burst - 1 and time.time() - started < burst_seconds:
					await asyncio.to_thread(poster.post, f"burst {posted}")
					posted += 1
				await asyncio.to_thread(poster.post, last)
				posted += 1
				posting = time.time() - started
				arrived = await asyncio.wait_for(asyncio.gather(*watchers), 600)
				elapsed = max(arrived) / 1000 - started
				row["throughput"] = {
					"messages": posted,
					"post_seconds": posting,
					"seconds": elapsed,
					"messages_per_s": posted / elapsed,
					"deliveries_per_s": posted * count / elapsed,
					"server_cpu_ms_per_message": (server.cpu() - cpu) / posted * 1000,
				}

			await asyncio.gather(*(context.close() for context in contexts), return_exceptions=True)
			await asyncio.sleep(2)
	finally:
		poster.close()

	return results


def browser_rss():
	"""Memory of every Chromium process (to report the load on the box)."""

	total = 0
	for process in psutil.Process().children(recursive=True):
		try:
			if "chrom" in process.name().lower():
				total += process.memory_info().rss
		except psutil.NoSuchProcess:
			pass

	return total
