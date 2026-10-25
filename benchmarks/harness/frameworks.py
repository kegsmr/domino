"""Each framework: how to install it (into the cache, never the repo), build it and serve its apps.

Every server is one process (plus a supervisor where the framework's own launcher insists),
listening on 127.0.0.1 on a free ephemeral port, and serving /counter, /todo and /chat plus
POST /bench/chat?text=... (the load generator's hook).
"""

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import psutil


HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
ROOT = BENCH.parent
APPS = BENCH / "apps"
CACHE = Path(os.environ.get("DOMINO_BENCH_CACHE", Path.home() / ".cache" / "domino-bench"))

# Pinned so a rerun measures the same thing; bump deliberately
PYTHON = "3.13"
PIP = {
	"fastapi": ["fastapi==0.162.0", "uvicorn[standard]==0.54.0"],
	"flask": ["flask==3.1.3", "gunicorn==26.2.0"],
	"nicegui": ["nicegui==3.18.0"],
	"reflex": ["reflex==0.10.0"],
}
NPM = ["react@19.3.1", "react-dom@19.3.1", "esbuild@0.28.2", "htmx.org@2.0.11", "htmx-ext-sse@2.2.4"]


def free_port():

	with socket.socket() as s:
		s.bind(("127.0.0.1", 0))
		return s.getsockname()[1]


def run(command, **kwargs):

	print("  $", " ".join(str(part) for part in command), flush=True)
	subprocess.run([str(part) for part in command], check=True, **kwargs)


def venv(name):
	"""The cache's virtualenv for `name`, created and filled with PIP[name] if needed."""

	path = CACHE / "venvs" / name
	python = path / "bin" / "python"
	marker = path / ".bench-installed"
	wanted = " ".join(PIP[name])
	if not marker.exists() or marker.read_text() != wanted:
		uv = shutil.which("uv")
		if uv:
			run([uv, "venv", "-q", "--allow-existing", "-p", PYTHON, path])
			run([uv, "pip", "install", "-q", "-p", python, *PIP[name]])
		else:
			run([sys.executable, "-m", "venv", path])
			run([python, "-m", "pip", "install", "-q", *PIP[name]])
		marker.write_text(wanted)

	return python


def node_modules():

	path = CACHE / "node"
	marker = path / ".bench-installed"
	wanted = " ".join(NPM)
	if not marker.exists() or marker.read_text() != wanted:
		path.mkdir(parents=True, exist_ok=True)
		if not (path / "package.json").exists():
			(path / "package.json").write_text('{"name": "domino-bench", "private": true}\n')
		run(["npm", "install", "--silent", "--no-audit", "--no-fund", *NPM], cwd=path)
		marker.write_text(wanted)

	return path / "node_modules"


def pip_version(python, package):

	return subprocess.run([str(python), "-c", f"import importlib.metadata as m; print(m.version({package!r}))"],
		capture_output=True, text=True, check=True).stdout.strip()


class Server:
	"""A running server: its process tree, CPU and memory."""


	def __init__(self, command, cwd, env, port, ready_path="/counter", timeout=180):

		self.port = port
		self.url = f"http://127.0.0.1:{port}"
		self.log = open(CACHE / "logs" / f"server-{port}.log", "w")
		self.process = subprocess.Popen([str(part) for part in command], cwd=cwd, env=env,
			stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
		self.ps = psutil.Process(self.process.pid)

		deadline = time.monotonic() + timeout
		while True:
			if self.process.poll() is not None:
				raise RuntimeError(f"server exited with {self.process.returncode}; see {self.log.name}")
			try:
				with urllib.request.urlopen(self.url + ready_path, timeout=5) as response:
					if response.status == 200:
						break
			except urllib.error.HTTPError as error:
				self.stop()
				raise RuntimeError(f"server answered {error.code}; see {self.log.name}")
			except OSError:
				pass
			if time.monotonic() > deadline:
				self.stop()
				raise RuntimeError(f"server didn't start; see {self.log.name}")
			time.sleep(0.2)


	def tree(self):

		processes = [self.ps]
		try:
			processes += self.ps.children(recursive=True)
		except psutil.NoSuchProcess:
			pass

		return processes


	def cpu(self):
		"""CPU seconds used so far by the whole process tree. On Linux, from each thread's
		schedstat (nanoseconds; /proc/PID/stat counts 10 ms ticks, too coarse for one click),
		which leaves out threads that have exited: thread pools here outlive a measurement."""

		total = 0.0
		for process in self.tree():
			try:
				tasks = Path(f"/proc/{process.pid}/task")
				if tasks.exists():
					for task in tasks.iterdir():
						try:
							total += int((task / "schedstat").read_text().split()[0]) / 1e9
						except (OSError, ValueError, IndexError):
							pass
				else:
					times = process.cpu_times()
					total += times.user + times.system
			except psutil.NoSuchProcess:
				pass

		return total


	def memory(self):
		"""Proportional set size of the tree, in bytes (RSS where PSS isn't available)."""

		total = 0
		for process in self.tree():
			try:
				info = process.memory_full_info()
				total += getattr(info, "pss", info.rss)
			except (psutil.NoSuchProcess, psutil.AccessDenied):
				pass

		return total


	def stop(self):

		processes = self.tree()
		for process in processes:
			try:
				process.send_signal(signal.SIGTERM)
			except psutil.NoSuchProcess:
				pass
		_, alive = psutil.wait_procs(processes, timeout=15)
		for process in alive:
			try:
				process.kill()
			except psutil.NoSuchProcess:
				pass
		psutil.wait_procs(alive, timeout=5)
		self.process.wait(5)
		self.log.close()


class Framework:

	name = ""
	label = ""
	# Selectors, where a framework's components render differently from the shared ids
	toggle = "#todos input[type=checkbox]"
	checkbox_index = 500
	# Tabs per browser context in the idle-memory test (Chromium allows 6 HTTP/1.1 connections
	# per host and context; a context per tab would need a renderer process per tab)
	tabs_per_context = 25


	def setup(self):
		pass


	def versions(self):
		return {}


	def start(self, api_port=None):
		raise NotImplementedError


class Domino(Framework):

	name = "domino"
	label = "Domino"


	def versions(self):

		commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
		version = next(line.split('"')[1] for line in (ROOT / "setup.py").read_text().splitlines() if "version=" in line)
		uvicorn = pip_version(sys.executable, "uvicorn")

		return {"domino": f"{version} ({commit}, this checkout)", "uvicorn": uvicorn, "python": sys.version.split()[0]}


	def start(self, api_port=None):

		port = free_port()
		env = dict(os.environ, PYTHONPATH=str(ROOT))
		command = [sys.executable, "-m", "domino", "serve", APPS / "domino", "--workers", "1", "--port", port]

		return Server(command, APPS / "domino", env, port)


class React(Framework):

	name = "react"
	label = "React + FastAPI"


	def setup(self):

		self.python = venv("fastapi")
		modules = node_modules()
		build = CACHE / "build" / "react"
		build.mkdir(parents=True, exist_ok=True)
		shutil.copy(APPS / "react" / "index.html", build / "index.html")
		run([modules / ".bin" / "esbuild", APPS / "react" / "src" / "main.jsx", "--bundle", "--minify", "--format=esm",
			"--jsx=automatic", "--define:process.env.NODE_ENV=\"production\"", f"--outfile={build / 'app.js'}",
			"--log-level=warning"], env=dict(os.environ, NODE_PATH=str(modules)))
		self.build = build


	def versions(self):

		modules = CACHE / "node" / "node_modules"
		read = lambda package: __import__("json").loads((modules / package / "package.json").read_text())["version"]

		return {"react": read("react"), "react-dom": read("react-dom"), "esbuild": read("esbuild"),
			"fastapi": pip_version(self.python, "fastapi"), "uvicorn": pip_version(self.python, "uvicorn")}


	def start(self, api_port=None):

		port = free_port()
		env = dict(os.environ, BENCH_BUILD=str(self.build))
		command = [self.python, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", port, "--log-level", "warning"]

		return Server(command, APPS / "react", env, port)


class HTMX(Framework):

	name = "htmx"
	label = "Flask + htmx"
	# Each tab holds an event stream, so at most 5 tabs to a context
	tabs_per_context = 5


	def setup(self):

		self.python = venv("flask")
		modules = node_modules()
		static = CACHE / "build" / "htmx-static"
		static.mkdir(parents=True, exist_ok=True)
		shutil.copy(modules / "htmx.org" / "dist" / "htmx.min.js", static / "htmx.min.js")
		shutil.copy(modules / "htmx-ext-sse" / "dist" / "sse.min.js", static / "sse.min.js")
		self.static = static


	def versions(self):

		modules = CACHE / "node" / "node_modules"
		read = lambda package: __import__("json").loads((modules / package / "package.json").read_text())["version"]

		return {"flask": pip_version(self.python, "flask"), "gunicorn": pip_version(self.python, "gunicorn"),
			"htmx.org": read("htmx.org"), "htmx-ext-sse": read("htmx-ext-sse")}


	def start(self, api_port=None):

		port = free_port()
		env = dict(os.environ, BENCH_STATIC=str(self.static))
		# One process, as for the others; a thread per request, and so per open event stream
		command = [self.python, "-m", "gunicorn", "app:app", "--bind", f"127.0.0.1:{port}", "--workers", "1",
			"--worker-class", "gthread", "--threads", "1024", "--worker-connections", "4096", "--keep-alive", "75", "--log-level", "warning"]

		return Server(command, APPS / "htmx", env, port)


class NiceGUI(Framework):

	name = "nicegui"
	label = "NiceGUI"
	toggle = "#todos .q-checkbox"


	def setup(self):

		self.python = venv("nicegui")


	def versions(self):

		return {"nicegui": pip_version(self.python, "nicegui"), "uvicorn": pip_version(self.python, "uvicorn")}


	def start(self, api_port=None):

		port = free_port()
		env = dict(os.environ, PORT=str(port))

		return Server([self.python, "app.py"], APPS / "nicegui", env, port)


class Reflex(Framework):

	name = "reflex"
	label = "Reflex"
	toggle = "#todos button[role=checkbox]"


	def setup(self):

		self.python = venv("reflex")
		# Reflex builds into the app's folder (.web/), so it runs from a copy in the cache
		self.app = CACHE / "build" / "reflex-app"
		shutil.copytree(APPS / "reflex", self.app, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
		self.env = dict(os.environ, PATH=f"{self.python.parent}:{os.environ['PATH']}", REFLEX_TELEMETRY_ENABLED="false")
		run([self.python, "-m", "reflex", "export", "--frontend-only", "--no-zip"], cwd=self.app, env=self.env)


	def versions(self):

		return {"reflex": pip_version(self.python, "reflex"), "granian": pip_version(self.python, "granian")}


	def start(self, api_port=None):

		port = free_port()
		command = [self.python, "-m", "reflex", "run", "--env", "prod", "--single-port", "--backend-port", port,
			"--backend-host", "127.0.0.1", "--loglevel", "warning"]
		env = dict(self.env)
		if api_port:
			# The frontend opens its socket to this absolute URL, so behind the latency proxy it must
			# name the proxy's port (the other frameworks use the page's own origin)
			env["REFLEX_API_URL"] = f"http://localhost:{api_port}"

		return Server(command, self.app, env, port, timeout=400)


ALL = [Domino(), React(), HTMX(), NiceGUI(), Reflex()]
BY_NAME = {framework.name: framework for framework in ALL}
