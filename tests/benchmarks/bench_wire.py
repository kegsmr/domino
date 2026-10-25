"""What goes over the WebSocket per update, and what it costs the server.

	python tests/benchmarks/bench_wire.py [--updates 200] [--only bytes|hidden|memory] [--no-patches]

1. bytes per update: for each case in wire_app.py (a counter, a todo list of 100 items where
   one changes, a chat of 200 messages where one is appended, a 500-row table where one cell
   changes, and two components of examples/instant that ship predicted states), the bytes of
   each event result or push as sent (raw) and after per-message deflate as uvicorn does it
   (window bits 12, memLevel 5, context takeover; emulated exactly with zlib over the same
   messages), the server's CPU per update (render, diff, JSON, uvicorn; for pushes also the
   GET that changes the data), and the HTML kept per page as the base for patches.
2. hidden tabs: server CPU for a chatty collection with 100 chat tabs, visible vs hidden.
3. memory per idle socket, with and without per-message deflate.

Each run starts its own server process (wire_app.py). Needs psutil and websockets. Not
collected by pytest.
"""

import argparse
import asyncio
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
import zlib
from pathlib import Path

import psutil
import websockets


HERE = Path(__file__).parent
ROOT = HERE.parent.parent

EVENT_CASES = ["counter", "todo", "stepper", "tabs"]
PUSH_CASES = ["chat", "table"]


def free_port():

	with socket.socket() as s:
		s.bind(("127.0.0.1", 0))
		return s.getsockname()[1]


class Server:


	def __init__(self, *flags):

		self.port = free_port()
		env = dict(os.environ, PYTHONPATH=str(ROOT))
		self.process = subprocess.Popen([sys.executable, str(HERE / "wire_app.py"), str(self.port), *flags], env=env)
		self.ps = psutil.Process(self.process.pid)
		self.url = f"http://127.0.0.1:{self.port}"

		deadline = time.monotonic() + 15
		while True:
			try:
				socket.create_connection(("127.0.0.1", self.port), 0.2).close()
				break
			except OSError:
				assert time.monotonic() < deadline, "server didn't start"
				time.sleep(0.05)


	def cpu(self):

		times = self.ps.cpu_times()

		return times.user + times.system


	def rss(self):

		return self.ps.memory_info().rss


	def get(self, path):

		with urllib.request.urlopen(self.url + path, timeout=30) as response:
			return response.read().decode()


	def stop(self):

		self.process.terminate()
		self.process.wait(10)


class Deflate:
	"""Server-to-client per-message deflate as uvicorn negotiates it, for counting bytes."""


	def __init__(self):

		self.compressor = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -12, 5)


	def size(self, text):

		data = self.compressor.compress(text.encode()) + self.compressor.flush(zlib.Z_SYNC_FLUSH)

		# The empty block at the end of each message isn't sent
		return len(data) - 4


def apply_patch(base, ops):
	"""What core.js does with {"patch": ops}: copies of the base's lines, and new text."""

	lines = base.split("\n")
	pieces = []
	for op in ops:
		if isinstance(op, str):
			pieces.append(op)
		else:
			pieces.extend(lines[op[0]:op[0] + op[1]])

	return "\n".join(pieces)


class Client:
	"""One tab's socket, keeping the HTML of each component like core.js does."""


	def __init__(self, server, case):

		self.server = server
		html = server.get(f"/{case}")
		self.page_id = re.search(r'data-domino-page="([^"]+)"', html).group(1)
		self.event_ids = re.findall(r'data-event-id="([^"]+)"', html)
		self.html = html
		self.bases = {}
		self.deflate = Deflate()
		self.ref = 0


	async def open(self, compression=None):

		self.ws = await websockets.connect(f"ws://127.0.0.1:{self.server.port}/_domino/ws", ping_interval=None,
			open_timeout=60, compression=compression, max_size=None)
		await self.ws.send(json.dumps({"type": "hello", "page_id": self.page_id, "patch": True}))
		assert json.loads(await self.ws.recv())["type"] == "ready"


	async def receive(self, kind):
		"""The next message of `kind` ("result" or "update"), and its sizes."""

		while True:
			text = await self.ws.recv()
			raw = len(text.encode())
			compressed = self.deflate.size(text)
			data = json.loads(text)
			if data.get("type") != kind:
				continue
			if "patch" in data:
				base_version, base = self.bases[data["id"]]
				assert base_version == data["base"], "base mismatch"
				data["html"] = apply_patch(base, data["patch"])
			if data.get("html"):
				self.bases[data["id"]] = (data["version"], data["html"])
			return data, raw, compressed


	async def event(self, event_id):

		self.ref += 1
		await self.ws.send(json.dumps({"type": "event", "ref": self.ref, "page_id": self.page_id, "event_id": event_id, "data": {}}))

		return await self.receive("result")


	async def close(self):

		await self.ws.close()


def events_for(case, client, count):
	"""The events to fire, in order: what a user of each component would click."""

	ids = client.event_ids
	if case == "counter":
		return [ids[0]] * count
	if case == "todo":
		return [ids[(i * 37) % len(ids)] for i in range(count)]
	if case == "stepper":
		fewer, more = ids[0], ids[1]
		# Up to 5 and back down, so each click changes something
		return [more if (i // 5) % 2 == 0 else fewer for i in range(count)]
	if case == "tabs":
		tabs = [event_id for event_id in ids if event_id.endswith("-click")]
		return [tabs[(i + 1) % len(tabs)] for i in range(count)]

	raise ValueError(case)


def measure_case(server, case, count):

	client = Client(server, case)

	async def run():
		await client.open()
		warmup = 5
		if case in EVENT_CASES:
			events = events_for(case, client, count + warmup)
			step = lambda i: client.event(events[i])
		else:
			async def step(_):
				await asyncio.get_running_loop().run_in_executor(None, server.get, f"/bump/{case}")
				return await client.receive("update")

		for i in range(warmup):
			await step(i)

		raw = compressed = patched = 0
		started = server.cpu()
		for i in range(warmup, warmup + count):
			data, size, deflated = await step(i)
			raw += size
			compressed += deflated
			patched += "patch" in data
		cpu = server.cpu() - started

		html = sum(len(html) for _, html in client.bases.values())
		await client.close()

		return {
			"raw": raw / count,
			"compressed": compressed / count,
			"cpu_ms": cpu / count * 1e3,
			"html": html,
			"patched": patched / count,
		}

	return asyncio.run(run())


def bytes_per_update(count, flags):

	print(f"1. Bytes per update ({count} updates each, after 5 to warm up){' ' + ' '.join(flags) if flags else ''}")
	print(f"  {'case':10} {'raw B':>9} {'deflate B':>10} {'server ms':>10} {'HTML B':>9} {'patched':>8}")
	results = {}
	for case in EVENT_CASES + PUSH_CASES:
		server = Server(*flags)
		try:
			r = results[case] = measure_case(server, case, count)
		finally:
			server.stop()
		print(f"  {case:10} {r['raw']:9.0f} {r['compressed']:10.0f} {r['cpu_ms']:10.3f} {r['html']:9} {r['patched']:8.0%}")

	return results


def hidden_tabs(tabs, bumps, flags):

	print(f"2. Server CPU for {bumps} chat messages with {tabs} tabs open{' ' + ' '.join(flags) if flags else ''}")

	for hidden in (False, True):
		server = Server(*flags)
		try:
			clients = [Client(server, "chat") for _ in range(tabs)]

			async def run():
				await asyncio.gather(*(client.open() for client in clients))
				if hidden:
					for client in clients:
						await client.ws.send(json.dumps({"type": "pause"}))
				await asyncio.sleep(0.5)

				received = [0]

				async def drain(client):
					try:
						async for _ in client.ws:
							received[0] += 1
					except websockets.ConnectionClosed:
						pass

				readers = [asyncio.ensure_future(drain(client)) for client in clients]
				loop = asyncio.get_running_loop()
				started = server.cpu()
				for _ in range(bumps):
					await loop.run_in_executor(None, server.get, "/bump/chat")
				# Until the server is idle again
				await asyncio.sleep(1)
				idle = server.cpu()
				while True:
					await asyncio.sleep(0.5)
					now = server.cpu()
					if now - idle < 0.01:
						break
					idle = now
				cpu = now - started
				messages = received[0]

				resumed = None
				if hidden:
					started = server.cpu()
					for client in clients:
						await client.ws.send(json.dumps({"type": "resume"}))
					await asyncio.sleep(1)
					resumed = server.cpu() - started

				for reader in readers:
					reader.cancel()
				await asyncio.gather(*(client.close() for client in clients), return_exceptions=True)

				return cpu, messages, received[0] - messages, resumed

			cpu, messages, after, resumed = asyncio.run(run())
		finally:
			server.stop()

		label = "hidden" if hidden else "visible"
		line = f"  {label:8} CPU {cpu * 1e3:8.1f} ms ({cpu / bumps * 1e3:6.1f} ms per message)  updates sent {messages}"
		if resumed is not None:
			line += f"  on showing them: CPU {resumed * 1e3:6.1f} ms, updates {after}"
		print(line)


def memory(count):

	print(f"3. Memory per idle socket ({count} sockets, browsers ask for compression)")

	for flags in ((), ("--no-compression",)):
		server = Server(*flags)
		try:
			clients = [Client(server, "counter") for _ in range(count)]
			time.sleep(0.5)
			before = server.rss()

			async def run():
				semaphore = asyncio.Semaphore(100)

				async def open_one(client):
					async with semaphore:
						await client.open(compression="deflate")

				await asyncio.gather(*(open_one(client) for client in clients))
				await asyncio.sleep(2)
				after = server.rss()
				await asyncio.gather(*(client.close() for client in clients))
				return after

			after = asyncio.run(run())
		finally:
			server.stop()

		label = "deflate off" if flags else "deflate on"
		print(f"  {label:12} {(after - before) / count / 1e3:6.1f} KB per socket")


def main():

	parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
	parser.add_argument("--updates", type=int, default=200)
	parser.add_argument("--tabs", type=int, default=100)
	parser.add_argument("--bumps", type=int, default=20)
	parser.add_argument("--sockets", type=int, default=500)
	parser.add_argument("--no-patches", action="store_true", help="send whole HTML, as before patches")
	parser.add_argument("--only", choices=["bytes", "hidden", "memory"], help="run one benchmark")
	args = parser.parse_args()

	flags = ("--no-patches",) if args.no_patches else ()

	if args.only in (None, "bytes"):
		bytes_per_update(args.updates, flags)
	if args.only in (None, "hidden"):
		hidden_tabs(args.tabs, args.bumps, flags)
	if args.only in (None, "memory"):
		memory(args.sockets)


if __name__ == "__main__":
	main()
