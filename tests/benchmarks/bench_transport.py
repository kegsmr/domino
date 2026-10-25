"""Compare the two transports: POST + Server-Sent Events on Werkzeug's threaded server (how
Domino served pages before the async core) against one WebSocket per tab on uvicorn.

	python tests/benchmarks/bench_transport.py [--pages 200 2000] [--events 1000] [--fanout 500]

Measures, with a fresh server process per run:
1. idle live pages: the server's memory and thread count with N tabs connected
2. event round trip for the counter, p50/p95: HTTP POST vs WebSocket
3. push fan-out: time from one refresh() until all connected pages have the update

Needs psutil and websockets. Not collected by pytest.
"""

import argparse
import asyncio
import http.client
import json
import os
import re
import socket
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psutil
import websockets


HERE = Path(__file__).parent
COMPRESSION = "deflate"
ROOT = HERE.parent.parent


def free_port():

	with socket.socket() as s:
		s.bind(("127.0.0.1", 0))
		return s.getsockname()[1]


class Server:


	def __init__(self, mode):

		self.mode = mode
		self.port = free_port()
		env = dict(os.environ, PYTHONPATH=str(ROOT))
		self.process = subprocess.Popen([sys.executable, str(HERE / "bench_app.py"), mode, str(self.port)], env=env)
		self.ps = psutil.Process(self.process.pid)

		deadline = time.monotonic() + 15
		while True:
			try:
				socket.create_connection(("127.0.0.1", self.port), 0.2).close()
				break
			except OSError:
				assert time.monotonic() < deadline, "server didn't start"
				time.sleep(0.05)


	def rss(self):

		return self.ps.memory_info().rss


	def threads(self):

		return self.ps.num_threads()


	def stop(self):

		self.process.terminate()
		self.process.wait(10)


def get(port, path):

	connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
	connection.request("GET", path)
	body = connection.getresponse().read().decode()
	connection.close()

	return body


def load_pages(port, count):

	def load(_):
		html = get(port, "/")
		page_id = re.search(r'data-domino-page="([^"]+)"', html).group(1)
		event_id = re.search(r'data-event-id="([^"]+)"', html).group(1)
		return page_id, event_id

	with ThreadPoolExecutor(16) as pool:
		return list(pool.map(load, range(count)))


class SSEClient:


	def __init__(self, port, page_id):

		self.port = port
		self.page_id = page_id
		self.received = []


	async def open(self):

		self.reader, self.writer = await asyncio.open_connection("127.0.0.1", self.port, limit=1 << 20)
		self.writer.write(f"GET /_domino/stream?page={self.page_id} HTTP/1.1\r\nHost: 127.0.0.1\r\nAccept: text/event-stream\r\n\r\n".encode())
		await self.writer.drain()
		status = await self.reader.readline()
		assert b" 200 " in status, status
		self.task = asyncio.ensure_future(self.read())


	async def read(self):

		while True:
			line = await self.reader.readline()
			if not line:
				return
			if b"data: " in line:
				self.received.append((time.perf_counter(), line))


	async def close(self):

		self.task.cancel()
		self.writer.close()


class WSClient:


	def __init__(self, port, page_id):

		self.port = port
		self.page_id = page_id
		self.received = []


	async def open(self):

		# Browsers ask for compression, so it's on unless --no-compression
		self.ws = await websockets.connect(f"ws://127.0.0.1:{self.port}/_domino/ws", ping_interval=None, open_timeout=60, compression=COMPRESSION)
		await self.ws.send(json.dumps({"type": "hello", "page_id": self.page_id}))
		assert json.loads(await self.ws.recv())["type"] == "ready"
		self.task = asyncio.ensure_future(self.read())


	async def read(self):

		async for message in self.ws:
			self.received.append((time.perf_counter(), message.encode()))


	async def close(self):

		self.task.cancel()
		await self.ws.close()


def client_class(mode):

	if mode == "wsgi":
		return SSEClient

	return WSClient


async def open_all(clients):

	# A few at a time, so the listen backlog doesn't overflow
	semaphore = asyncio.Semaphore(100)

	async def open_one(client):
		async with semaphore:
			await client.open()

	await asyncio.gather(*(open_one(client) for client in clients))


def idle_pages(mode, count):

	server = Server(mode)
	try:
		load_pages(server.port, 1)
		time.sleep(0.5)
		base_rss, base_threads = server.rss(), server.threads()

		pages = load_pages(server.port, count)
		time.sleep(0.5)
		pages_rss = server.rss()

		async def run():
			clients = [client_class(mode)(server.port, page_id) for page_id, _ in pages]
			await open_all(clients)
			await asyncio.sleep(2)
			result = (server.rss(), server.threads())
			await asyncio.gather(*(client.close() for client in clients))
			return result

		open_rss, open_threads = asyncio.run(run())
	finally:
		server.stop()

	return {
		"pages": count,
		"base_mb": base_rss / 1e6,
		"page_kb": (pages_rss - base_rss) / count / 1e3,
		"connection_kb": (open_rss - pages_rss) / count / 1e3,
		"total_mb": open_rss / 1e6,
		"threads_before": base_threads,
		"threads": open_threads,
	}


def percentiles(samples):

	samples = sorted(samples)

	return {
		"p50_ms": statistics.median(samples) * 1e3,
		"p95_ms": samples[int(len(samples) * 0.95)] * 1e3,
	}


def post_latency(mode, count):

	server = Server(mode)
	try:
		((page_id, event_id),) = load_pages(server.port, 1)
		connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=30)
		body = json.dumps({"page_id": page_id, "event_id": event_id, "data": {}})
		samples = []
		for i in range(count + 50):
			started = time.perf_counter()
			connection.request("POST", "/_domino/events", body, {"Content-Type": "application/json"})
			response = connection.getresponse()
			assert response.status == 200
			response.read()
			if i >= 50:
				samples.append(time.perf_counter() - started)
		connection.close()
	finally:
		server.stop()

	return percentiles(samples)


def ws_latency(count):

	server = Server("asgi")
	try:
		((page_id, event_id),) = load_pages(server.port, 1)

		async def run():
			samples = []
			async with websockets.connect(f"ws://127.0.0.1:{server.port}/_domino/ws", ping_interval=None) as ws:
				await ws.send(json.dumps({"type": "hello", "page_id": page_id}))
				await ws.recv()
				for i in range(count + 50):
					started = time.perf_counter()
					await ws.send(json.dumps({"type": "event", "ref": i, "page_id": page_id, "event_id": event_id, "data": {}}))
					result = json.loads(await ws.recv())
					assert result["status"] == 200
					if i >= 50:
						samples.append(time.perf_counter() - started)
			return samples

		samples = asyncio.run(run())
	finally:
		server.stop()

	return percentiles(samples)


def fanout(mode, count, rounds=5):

	server = Server(mode)
	try:
		pages = load_pages(server.port, count)

		async def run():
			clients = [client_class(mode)(server.port, page_id) for page_id, _ in pages]
			await open_all(clients)
			await asyncio.sleep(1)
			times = []
			loop = asyncio.get_running_loop()
			for tick in range(1, rounds + 1):
				marker = f"Ticks: {tick}".encode()
				started = time.perf_counter()
				await loop.run_in_executor(None, get, server.port, "/bump")
				while not all(any(marker in line for _, line in client.received) for client in clients):
					await asyncio.sleep(0.002)
				last = max(
					received for client in clients for received, line in client.received
					if marker in line
				)
				times.append(last - started)
			await asyncio.gather(*(client.close() for client in clients))
			return times

		times = asyncio.run(run())
	finally:
		server.stop()

	return {"pages": count, "median_ms": statistics.median(times) * 1e3, "max_ms": max(times) * 1e3}


def main():

	global COMPRESSION

	parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
	parser.add_argument("--pages", type=int, nargs="+", default=[200, 2000])
	parser.add_argument("--events", type=int, default=1000)
	parser.add_argument("--fanout", type=int, default=500)
	parser.add_argument("--no-compression", action="store_true", help="WebSocket clients don't ask for permessage-deflate")
	parser.add_argument("--only", choices=["idle", "latency", "fanout"], help="run one benchmark")
	args = parser.parse_args()

	if args.no_compression:
		COMPRESSION = None

	names = {"wsgi": "SSE, Werkzeug threaded", "asgi": "WebSocket, uvicorn"}

	if args.only in (None, "idle"):
		idle(args.pages, names)
	if args.only in (None, "latency"):
		latency(args.events)
	if args.only in (None, "fanout"):
		fanouts(args.fanout, names)


def idle(counts, names):

	print("1. Idle live pages")
	for count in counts:
		for mode in ("wsgi", "asgi"):
			r = idle_pages(mode, count)
			print(f"  {names[mode]:24} N={count:5}  per connection {r['connection_kb']:7.1f} KB  "
				f"(+ {r['page_kb']:5.1f} KB per page state)  RSS {r['total_mb']:6.1f} MB  "
				f"threads {r['threads_before']} -> {r['threads']}")


def latency(events):

	print(f"2. Event round trip ({events} events, counter)")
	for label, result in (
		("HTTP POST, Werkzeug", post_latency("wsgi", events)),
		("HTTP POST, uvicorn", post_latency("asgi", events)),
		("WebSocket, uvicorn", ws_latency(events)),
	):
		print(f"  {label:24} p50 {result['p50_ms']:6.2f} ms  p95 {result['p95_ms']:6.2f} ms")


def fanouts(count, names):

	print(f"3. Push fan-out to {count} pages")
	for mode in ("wsgi", "asgi"):
		r = fanout(mode, count)
		print(f"  {names[mode]:24} median {r['median_ms']:7.1f} ms  max {r['max_ms']:7.1f} ms")


if __name__ == "__main__":
	main()
