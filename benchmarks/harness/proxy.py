"""A TCP proxy that adds network latency, the same for every framework and every protocol.

	python proxy.py LISTEN_PORT TARGET_PORT

Each chunk is delivered half the round trip after it was sent, in each direction, in order, so
an HTTP request on an open connection takes one round trip, a WebSocket or Server-Sent Events
message half of one each way, and a new connection one more (the TCP handshake). Chromium's
own throttling (CDP Network.emulateNetworkConditions) only delays HTTP responses' headers, not
WebSocket frames or streamed bodies, so it would favour the frameworks that talk over a socket.

The round trip in ms is read from stdin, one number per line (0 at first), and applies to
chunks sent from then on.
"""

import asyncio
import collections
import os
import socket
import sys


rtt = 0.0


async def pipe(reader, writer, extra_until=0.0):

	loop = asyncio.get_running_loop()
	queue = collections.deque()
	ready = asyncio.Event()
	done = False

	async def receive():
		nonlocal done
		try:
			while data := await reader.read(65536):
				now = loop.time()
				due = max(now, extra_until) + rtt / 2000
				# Never overtake the chunk before
				if queue and queue[-1][0] > due:
					due = queue[-1][0]
				queue.append((due, data))
				ready.set()
		except (ConnectionError, OSError):
			pass
		finally:
			done = True
			ready.set()

	async def send():
		try:
			while True:
				while not queue:
					if done:
						return
					ready.clear()
					await ready.wait()
				due, data = queue.popleft()
				delay = due - loop.time()
				if delay > 0:
					await asyncio.sleep(delay)
				writer.write(data)
				await writer.drain()
		except (ConnectionError, OSError):
			pass
		finally:
			try:
				writer.close()
			except Exception:
				pass

	await asyncio.gather(receive(), send())


async def handle(client_reader, client_writer, target):

	loop = asyncio.get_running_loop()
	# The handshake: the client's first bytes leave one round trip after it connects
	handshake = loop.time() + rtt / 1000
	try:
		server_reader, server_writer = await asyncio.open_connection("127.0.0.1", target)
	except OSError:
		client_writer.close()
		return
	for writer in (client_writer, server_writer):
		sock = writer.get_extra_info("socket")
		if sock is not None:
			sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

	await asyncio.gather(pipe(client_reader, server_writer, handshake), pipe(server_reader, client_writer))


async def control():

	global rtt
	loop = asyncio.get_running_loop()
	reader = asyncio.StreamReader()
	await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
	while line := await reader.readline():
		rtt = float(line)
		print(f"rtt {rtt:g}", flush=True)
	# stdin closed: the harness is gone
	os._exit(0)


async def main(listen, target):

	server = await asyncio.start_server(lambda r, w: handle(r, w, target), "127.0.0.1", listen, backlog=4096)
	print("ready", flush=True)
	async with server:
		await control()


if __name__ == "__main__":
	asyncio.run(main(int(sys.argv[1]), int(sys.argv[2])))
