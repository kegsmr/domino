"""Compare `domino serve --workers 1` (uvicorn alone) with N workers behind the router, on
bench_app.py's /busy page, whose page loads and click handler each do ~5 ms of Python work.

	python tests/benchmarks/bench_serve.py [--workers 1 2 4] [--clients 32] [--seconds 10]

Measures, with a fresh `domino serve` per run:
1. page loads per second: --clients keep-alive connections loading /busy over and over
2. events per second and their round trip, p50/p95: --clients tabs, each clicking over its
   WebSocket as fast as the answers come
3. the router's cost: one tab clicking the plain counter (no work), round trip p50/p95

The load generator runs on the same machine, so it takes CPU from the server. Needs websockets.
Not collected by pytest.
"""

import argparse
import asyncio
import json
import os
import re
import socket
import statistics
import subprocess
import sys
import time
from pathlib import Path

import websockets


HERE = Path(__file__).parent
ROOT = HERE.parent.parent


def free_port():

	with socket.socket() as s:
		s.bind(("127.0.0.1", 0))
		return s.getsockname()[1]


class Server:


	def __init__(self, workers):

		self.port = free_port()
		env = dict(os.environ, PYTHONPATH=str(ROOT))
		command = "import sys; from domino.cli import main; sys.exit(main(sys.argv[1:]))"
		self.process = subprocess.Popen(
			[sys.executable, "-c", command, "serve", str(HERE / "bench_app.py"), "--workers", str(workers), "--port", str(self.port)],
			env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

		deadline = time.monotonic() + 60
		while True:
			try:
				socket.create_connection(("127.0.0.1", self.port), 0.2).close()
				break
			except OSError:
				assert time.monotonic() < deadline, "server didn't start"
				time.sleep(0.05)


	def stop(self):

		self.process.terminate()
		self.process.wait(30)


class HTTPClient:
	"""A keep-alive HTTP/1.1 connection, cheap on the client's CPU."""


	def __init__(self, port):

		self.port = port


	async def open(self):

		self.reader, self.writer = await asyncio.open_connection("127.0.0.1", self.port, limit=1 << 20)


	async def get(self, path):

		self.writer.write(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n\r\n".encode())
		head = await self.reader.readuntil(b"\r\n\r\n")
		status = int(head.split(b" ", 2)[1])
		length = int(re.search(rb"(?i)content-length: *(\d+)", head).group(1))
		body = await self.reader.readexactly(length)

		return status, body


	def close(self):

		self.writer.close()


def percentiles(samples):

	samples = sorted(samples)

	return {
		"p50_ms": statistics.median(samples) * 1e3,
		"p95_ms": samples[int(len(samples) * 0.95)] * 1e3,
	}


async def page_loads(port, clients, seconds):

	connections = [HTTPClient(port) for _ in range(clients)]
	await asyncio.gather(*(connection.open() for connection in connections))
	done = 0
	stop = time.perf_counter() + seconds

	async def load(connection):
		nonlocal done
		while time.perf_counter() < stop:
			status, _ = await connection.get("/busy")
			assert status == 200
			done += 1

	started = time.perf_counter()
	await asyncio.gather(*(load(connection) for connection in connections))
	elapsed = time.perf_counter() - started
	for connection in connections:
		connection.close()

	return done / elapsed


async def open_tab(port, path):

	connection = HTTPClient(port)
	await connection.open()
	_, html = await connection.get(path)
	connection.close()
	page_id = re.search(rb'data-domino-page="([^"]+)"', html).group(1).decode()
	event_id = re.search(rb'data-event-id="([^"]+)"', html).group(1).decode()

	ws = await websockets.connect(f"ws://127.0.0.1:{port}/_domino/ws?page={page_id}", ping_interval=None, open_timeout=60)
	await ws.send(json.dumps({"type": "hello", "page_id": page_id}))
	assert json.loads(await ws.recv())["type"] == "ready"

	return ws, page_id, event_id


async def click(ws, ref, page_id, event_id):

	started = time.perf_counter()
	await ws.send(json.dumps({"type": "event", "ref": ref, "page_id": page_id, "event_id": event_id, "data": {}}))
	while True:
		message = json.loads(await ws.recv())
		if message.get("type") == "result":
			assert message["status"] == 200, message
			return time.perf_counter() - started


async def events(port, clients, seconds, path="/busy"):

	tabs = await asyncio.gather(*(open_tab(port, path) for _ in range(clients)))
	samples = []
	stop = time.perf_counter() + seconds

	async def run(ws, page_id, event_id):
		ref = 0
		while time.perf_counter() < stop:
			ref += 1
			samples.append(await click(ws, ref, page_id, event_id))

	started = time.perf_counter()
	await asyncio.gather(*(run(*tab) for tab in tabs))
	elapsed = time.perf_counter() - started
	await asyncio.gather(*(ws.close() for ws, _, _ in tabs))

	return dict(percentiles(samples), per_second=len(samples) / elapsed)


async def round_trip(port, count=1000):

	ws, page_id, event_id = await open_tab(port, "/")
	samples = []
	for ref in range(count + 50):
		took = await click(ws, ref, page_id, event_id)
		if ref >= 50:
			samples.append(took)
	await ws.close()

	return percentiles(samples)


def measure(workers, clients, seconds):

	server = Server(workers)
	try:
		# Warm up every worker
		asyncio.run(page_loads(server.port, clients, 1))
		loads = asyncio.run(page_loads(server.port, clients, seconds))
		clicks = asyncio.run(events(server.port, clients, seconds))
		idle = asyncio.run(round_trip(server.port))
	finally:
		server.stop()

	return loads, clicks, idle


def main():

	parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
	parser.add_argument("--workers", type=int, nargs="+", default=sorted({1, 2, os.cpu_count() or 1}))
	parser.add_argument("--clients", type=int, default=32)
	parser.add_argument("--seconds", type=float, default=10)
	args = parser.parse_args()

	print(f"{os.cpu_count()} CPUs, {args.clients} clients, {args.seconds:g} s per measurement")
	print(f"{'workers':>8} {'loads/s':>9} {'events/s':>9} {'event p50':>10} {'event p95':>10}   {'idle p50':>9} {'idle p95':>9}")
	for workers in args.workers:
		loads, clicks, idle = measure(workers, args.clients, args.seconds)
		print(f"{workers:>8} {loads:9.0f} {clicks['per_second']:9.0f} {clicks['p50_ms']:8.1f}ms {clicks['p95_ms']:8.1f}ms"
			f"   {idle['p50_ms']:7.2f}ms {idle['p95_ms']:7.2f}ms", flush=True)


if __name__ == "__main__":
	main()
