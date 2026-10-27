"""Server CPU for many tabs, each watching its own slice of a busy collection.

	python tests/benchmarks/bench_queries.py [tabs] [writes] [mongodb url]

Each tab shows one user's open tasks (find({"owner": ..., "done": False})), with 20 users and
200 tasks. Each write updates one random task (its text, or done). Before per-query
subscriptions, every write re-rendered every tab; now only the tabs of the task's owner. With a
MongoDB URL (a replica set) the collection is a named one, so changes arrive by change stream.
"""

import random
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import domino.tags as t  # noqa: E402
from domino import Collection, Domino, mongo, wait  # noqa: E402
from domino.components import Document  # noqa: E402


USERS = 20
TASKS = 200


def main():

	arguments = sys.argv[1:] + [None] * 3
	tabs = int(arguments[0] or 200)
	writes = int(arguments[1] or 200)
	url = arguments[2]

	if url:
		mongo.connect(url)
		tasks = Collection(f"bench_{uuid.uuid4().hex[:8]}")
		while not tasks.store().watching:
			time.sleep(0.02)
	else:
		tasks = Collection()

	random_tasks = random.Random(1)
	ids = [tasks.insert({"owner": f"user{n % USERS}", "text": f"Task {n}", "done": random_tasks.random() < 0.5}) for n in range(TASKS)]
	wait()

	renders = [0]

	class Open(t.ul):

		owner = None

		def render(self):
			renders[0] += 1
			return [t.li() [task["text"]] for task in tasks.find({"owner": self.owner, "done": False}, sort="text")]

	app = Domino(__name__)
	app.config["DOMINO_MAX_PAGES"] = 100000

	@app.route("/<int:n>")
	def index(n):
		return Document() [Open(owner=f"user{n % USERS}")]

	client = app.test_client()
	for n in range(tabs):
		assert client.get(f"/{n}").status_code == 200

	renders[0] = 0
	random_writes = random.Random(2)
	cpu = time.process_time()
	start = time.perf_counter()

	for n in range(writes):
		key = random_writes.choice(ids)
		if n % 2:
			tasks.update({"_id": key}, {"$set": {"text": f"Task {key} v{n}"}})
		else:
			tasks.update({"_id": key}, {"$set": {"done": random_writes.random() < 0.5}})
	wait()

	cpu = time.process_time() - cpu
	took = time.perf_counter() - start
	store = "memory"
	if url:
		store = "MongoDB"
	print(f"{store}: {tabs} tabs, {writes} writes: {renders[0]} renders, {cpu:.2f} s CPU ({cpu / writes * 1000:.2f} ms per write), {took:.2f} s")

	if url:
		tasks.raw_collection().drop()


if __name__ == "__main__":
	main()
