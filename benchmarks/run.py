"""Domino against its competitors: the same three apps, measured the same way on the same machine.

	python benchmarks/run.py [--frameworks domino,react,htmx,nicegui,reflex] [--rounds 2] [--quick]

Installs each competitor into its own virtualenv or node folder under ~/.cache/domino-bench
(DOMINO_BENCH_CACHE to change it), never in the repository; Domino itself runs from this
checkout. Then, for each framework, with a fresh server per group of measurements:

1. page weight: bytes of a cold load of each app;
2. first load: first contentful paint and the first click that works, at 0 and 100 ms round trip;
3. click latency at 0, 100 and 300 ms round trip (a TCP proxy adds it, see harness/proxy.py):
   the counter (UI state), a todo list of 1,000 items' toggle and add (server data), with the
   server's CPU and the bytes on the wire per interaction at 0 ms;
4. chat fan-out to 2, 10 and 50 tabs: Send-to-every-tab latency, and burst throughput;
5. server memory per idle connected tab (the chat open in 100 and 500 tabs);
6. lines of app code.

Rounds 1-3 repeat (--rounds), the frameworks taking turns, so slow moments of a shared machine
spread over all of them. Writes benchmarks/results/<date>.json, the tables of
benchmarks/RESULTS.md (between its markers; the text around them is kept) and charts.
Needs playwright (with Chromium), psutil and matplotlib in the Python running this; uv and npm
to install the competitors.
"""

import argparse
import asyncio
import datetime
import json
import os
import platform
import shutil
import sys
import time
from pathlib import Path

import psutil
from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from harness import frameworks, loc, report, scenarios  # noqa: E402
from harness.browser import merge  # noqa: E402


def load():

	return list(os.getloadavg())


def log(*parts):

	print(time.strftime("%H:%M:%S"), *parts, flush=True)


async def run_round(browser, framework, config, record):
	"""The latency measurements: page weight, first loads, click latency."""

	server = framework.start()
	try:
		if config.page_weight:
			log(framework.name, "page weight")
			record.setdefault("page_weight", []).append(await scenarios.page_weights(browser, server.url, config.weight_runs))
		log(framework.name, "first loads, 0 ms")
		record.setdefault("first_load", {}).setdefault("0", []).append(
			await scenarios.first_loads(browser, framework, server.url, config.load_runs))
	finally:
		server.stop()

	# Behind the latency proxy (Reflex's frontend has to be told the proxy's port)
	proxy_port = frameworks.free_port()
	server = framework.start(api_port=proxy_port)
	proxy = scenarios.Proxy(server.port, port=proxy_port)
	try:
		idle = scenarios.idle_cpu_rate(server)
		record.setdefault("idle_cpu", []).append(idle)
		log(framework.name, "first loads, 100 ms")
		proxy.set(100)
		record["first_load"].setdefault("100", []).append(
			await scenarios.first_loads(browser, framework, proxy.url, config.load_runs))
		log(framework.name, "click latency", config.rtts)
		record.setdefault("interactions", []).append(
			await scenarios.interactions(browser, framework, server, proxy, config.rtts, config.clicks, idle))
	finally:
		proxy.stop()
		server.stop()


async def run_load(browser, framework, config, record):
	"""The measurements under load: chat fan-out and idle memory."""

	server = framework.start()
	try:
		log(framework.name, "chat fan-out", config.tabs)
		record["fanout"] = await scenarios.fanout(browser, server, config.tabs, config.messages, config.burst)
	finally:
		server.stop()

	server = framework.start()
	try:
		log(framework.name, "idle memory", config.idle_tabs)
		record["idle_memory"] = await scenarios.idle_memory(browser, server, config.idle_tabs, framework.tabs_per_context)
		record["server_baseline_mb"] = record["idle_memory"][config.idle_tabs[0]]["before_mb"]
	finally:
		server.stop()


def combine(record):
	"""Merge the rounds' samples."""

	out = {}
	if "page_weight" in record:
		out["page_weight"] = {app: {key: (merge([run[app][key] for run in record["page_weight"]]) if key != "encodings" else value)
			for key, value in record["page_weight"][-1][app].items()} for app in record["page_weight"][-1]}
	out["first_load"] = {rtt: {app: {metric: merge([run[app][metric] for run in runs]) for metric in runs[-1][app]}
		for app in runs[-1]} for rtt, runs in record.get("first_load", {}).items()}
	interactions = {}
	for run in record.get("interactions", []):
		for rtt, row in run.items():
			for key, value in row.items():
				interactions.setdefault(str(rtt), {}).setdefault(key, []).append(value)
	out["interactions"] = {rtt: {key: (merge(values) if isinstance(values[0], dict) else sum(values) / len(values))
		for key, values in row.items()} for rtt, row in interactions.items()}
	for key in ("fanout", "idle_memory", "server_baseline_mb", "idle_cpu"):
		if key in record:
			out[key] = record[key]

	return out


def environment(browser_version):

	cpu = platform.processor() or ""
	try:
		cpu = next(line.split(":", 1)[1].strip() for line in open("/proc/cpuinfo") if line.startswith("model name"))
	except (OSError, StopIteration):
		pass

	return {
		"date": datetime.datetime.now().isoformat(timespec="seconds"),
		"os": platform.platform(),
		"cpu": cpu,
		"cores": os.cpu_count(),
		"memory_gb": round(psutil.virtual_memory().total / 1e9, 1),
		"python": sys.version.split()[0],
		"chromium": browser_version,
		"playwright": __import__("importlib.metadata").metadata.version("playwright"),
		"node": shutil.which("node") and os.popen("node --version").read().strip(),
	}


async def main(config):

	selected = [frameworks.BY_NAME[name] for name in config.frameworks]
	(frameworks.CACHE / "logs").mkdir(parents=True, exist_ok=True)

	log("setting up", ", ".join(framework.name for framework in selected))
	skipped = {}
	ready = []
	for framework in selected:
		try:
			framework.setup()
			ready.append(framework)
		except Exception as error:
			log(framework.name, "can't be set up:", error)
			skipped[framework.name] = f"setup failed: {error}"

	results = {"frameworks": {}, "skipped": skipped, "loc": loc.count(), "load": {"start": load()}}
	records = {framework.name: {} for framework in ready}
	started = time.monotonic()

	async with async_playwright() as playwright:
		# Tabs of one context can share a renderer process; contexts can't
		browser = await playwright.chromium.launch(args=["--renderer-process-limit=24"])
		results["environment"] = environment(browser.version)
		try:
			for number in range(config.rounds):
				order = ready[number % len(ready):] + ready[:number % len(ready)]
				for framework in order:
					log(f"round {number + 1}/{config.rounds}:", framework.label)
					config.page_weight = number == 0
					results["load"].setdefault(framework.name, []).append(load())
					await run_round(browser, framework, config, records[framework.name])
			if not config.no_load:
				for framework in ready:
					log("load:", framework.label)
					results["load"].setdefault(framework.name, []).append(load())
					await run_load(browser, framework, config, records[framework.name])
		finally:
			await browser.close()

	for framework in ready:
		results["frameworks"][framework.name] = {"label": framework.label, "versions": framework.versions(),
			**combine(records[framework.name])}
	results["load"]["end"] = load()
	results["config"] = {key: value for key, value in vars(config).items() if key != "page_weight"}
	results["minutes"] = round((time.monotonic() - started) / 60, 1)

	out = HERE / "results" / f"{datetime.date.today().isoformat()}.json"
	if config.quick:
		out = out.with_name(out.stem + "-quick.json")
	out.parent.mkdir(exist_ok=True)
	out.write_text(json.dumps(results, indent=1))
	log("wrote", out)

	if not config.quick:
		report.write(results, HERE / "RESULTS.md", HERE / "results", out.name)
		log("wrote", HERE / "RESULTS.md")
	report.charts(results, Path(config.charts), HERE / "results" if not config.quick else None)


def parse():

	parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
	parser.add_argument("--frameworks", default=",".join(framework.name for framework in frameworks.ALL),
		type=lambda value: value.split(","))
	parser.add_argument("--rounds", type=int, default=2)
	parser.add_argument("--quick", action="store_true", help="few samples, to try the pipeline (results-quick.json, no RESULTS.md)")
	parser.add_argument("--no-load", action="store_true", help="skip chat fan-out and idle memory")
	parser.add_argument("--charts", default="/tmp/claude-0/s", help="where PNG charts go")
	config = parser.parse_args()

	config.rtts = [0, 100, 300]
	if config.quick:
		config.rounds = 1
		config.weight_runs, config.load_runs, config.clicks = 1, 2, 4
		config.tabs, config.messages, config.burst, config.idle_tabs = [2, 5], 3, 30, [20]
	else:
		config.weight_runs, config.load_runs, config.clicks = 3, 7, 15
		config.tabs, config.messages, config.burst, config.idle_tabs = [2, 10, 50], 10, 200, [100, 500]

	return config


if __name__ == "__main__":
	asyncio.run(main(parse()))
