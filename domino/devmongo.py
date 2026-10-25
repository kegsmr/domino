"""A local MongoDB for development, like the one `meteor run` starts: downloaded once into
~/.domino/mongodb (or $DOMINO_HOME/mongodb), with its data in the app's .domino/ folder."""

import atexit
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
import zipfile
from contextlib import contextmanager
from pathlib import Path


INDEX_URL = "https://downloads.mongodb.org/full.json"

DEFAULT_VERSION = "7.0"

REPLICA_SET = "rs0"

# Opts out of the development MongoDB, like the setting {"mongo": {"auto": false}}
ENV_DISABLE = "DOMINO_NO_MONGO"

# Linux build used when the distro isn't one MongoDB builds for
FALLBACK_TARGET = "ubuntu2204"

ARCHES = {
	"x86_64": "x86_64",
	"amd64": "x86_64",
	"aarch64": "aarch64",
	"arm64": "aarch64",
}


class DevMongoError(RuntimeError):
	"""The development MongoDB couldn't be downloaded or started."""


def log(message):

	print(f"domino: {message}", file=sys.stderr, flush=True)


def domino_home(environ=None):

	if environ is None:
		environ = os.environ

	if environ.get("DOMINO_HOME"):
		return Path(environ["DOMINO_HOME"])

	return Path.home() / ".domino"


def disabled_reason(settings, environ=None):
	"""Why the app shouldn't get a development MongoDB, or None if it should."""

	if environ is None:
		environ = os.environ

	mongo = settings.get("mongo")
	if not isinstance(mongo, dict):
		mongo = {}

	if mongo.get("url"):
		return "settings mongo.url"

	if environ.get(ENV_DISABLE, "").strip().lower() not in ("", "0", "false", "no"):
		return "disabled"

	if mongo.get("auto") is False:
		return "disabled"

	return None


def database_name(app_folder):

	name = re.sub(r"[^A-Za-z0-9_-]", "", Path(app_folder).resolve().name)

	return name or "domino"


def mongo_url(port, dbname):

	return f"mongodb://127.0.0.1:{port}/{dbname}?replicaSet={REPLICA_SET}&directConnection=true"


# Choosing a build


def read_os_release(path="/etc/os-release"):

	try:
		text = Path(path).read_text(encoding="utf-8")
	except OSError:
		return {}

	return parse_os_release(text)


def parse_os_release(text):

	fields = {}
	for line in text.splitlines():
		name, sep, value = line.partition("=")
		if sep:
			fields[name.strip()] = value.strip().strip("\"'")

	return fields


def linux_targets(os_release):
	"""MongoDB build targets that suit this distro, best first."""

	distro = os_release.get("ID", "").lower()
	version = os_release.get("VERSION_ID", "")
	major = version.split(".")[0]
	like = os_release.get("ID_LIKE", "").lower().split()

	if distro == "ubuntu":
		return ["ubuntu" + version.replace(".", "")]

	if distro == "debian":
		return ["debian" + major]

	if distro == "amzn":
		return ["amazon" + major]

	if distro in ("rhel", "centos", "rocky", "almalinux", "ol") or "rhel" in like:
		return ["rhel" + major, "rhel" + major + "0"]

	if distro in ("sles", "opensuse-leap"):
		return ["suse" + major]

	return []


def target_version(target):

	digits = re.sub(r"\D", "", target)

	return int(digits or 0)


def release_key(version):

	return tuple(int(part) for part in version.split("."))


def select_download(index, major=DEFAULT_VERSION, system=None, machine=None, os_release=None):
	"""The newest production release of `major` built for this machine, as a dict with
	version, target, url, sha256, sha1 and note (a line worth logging, or None)."""

	if system is None:
		system = platform.system()

	if machine is None:
		machine = platform.machine()

	major = str(major)
	arch = ARCHES.get(machine.lower(), machine.lower())

	releases = [
		release for release in index.get("versions", [])
		if release.get("production_release") and not release.get("release_candidate")
		and "-" not in release["version"]
		and (release["version"] == major or release["version"].startswith(major + "."))
	]
	releases.sort(key=lambda release: release_key(release["version"]), reverse=True)

	if not releases:
		raise DevMongoError(f"No MongoDB {major} production release found in {INDEX_URL}")

	for release in releases:
		download = pick_build(release["downloads"], system, arch, os_release)
		if download is not None:
			download["version"] = release["version"]
			return download

	raise DevMongoError(f"No MongoDB {major} build for {system} {machine}")


def pick_build(downloads, system, arch, os_release):

	# Community builds only: Linux ones are "targeted", macOS and Windows ones "base".
	# macOS calls the ARM architecture arm64, Linux aarch64
	builds = {}
	for download in downloads:
		download_arch = ARCHES.get(download.get("arch", ""), download.get("arch"))
		if download.get("edition") in ("targeted", "base") and download_arch == arch:
			builds.setdefault(download["target"], download)

	if system == "Darwin":
		return describe(builds.get("macos"), None)

	if system == "Windows":
		return describe(builds.get("windows"), None)

	if system != "Linux":
		return None

	if os_release is None:
		os_release = read_os_release()

	for target in linux_targets(os_release):
		if target in builds:
			return describe(builds[target], None)

	ubuntus = sorted((target for target in builds if target.startswith("ubuntu")), key=target_version, reverse=True)
	if not ubuntus:
		return None

	name = os_release.get("PRETTY_NAME") or "this Linux distribution"
	wanted = linux_targets(os_release)

	# A newer Ubuntu than MongoDB builds for runs the newest build that's older than it
	if wanted and wanted[0].startswith("ubuntu"):
		older = [target for target in ubuntus if target_version(target) <= target_version(wanted[0])]
		if older:
			return describe(builds[older[0]], f"no MongoDB build for {name}; using the {older[0]} build")

	target = FALLBACK_TARGET
	if target not in builds:
		target = ubuntus[0]

	return describe(builds[target], f"no MongoDB build for {name}; trying the {target} build")


def describe(download, note):

	if download is None:
		return None

	archive = download["archive"]

	return {
		"target": download["target"],
		"url": archive["url"],
		"sha256": archive.get("sha256"),
		"sha1": archive.get("sha1"),
		"note": note,
	}


# Downloading


def fetch_index():

	log(f"Looking up MongoDB releases at {INDEX_URL}")

	with urllib.request.urlopen(INDEX_URL, timeout=60) as response:
		return json.load(response)


def binary_name():

	if os.name == "nt":
		return "mongod.exe"

	return "mongod"


def cached_mongod(cache, major):
	"""The newest mongod already downloaded for `major`, so later runs work offline."""

	major = str(major)
	found = []

	if cache.is_dir():
		for folder in cache.iterdir():
			version = folder.name
			if not re.fullmatch(r"\d+(\.\d+)*", version):
				continue
			if version != major and not version.startswith(major + "."):
				continue
			if (folder / "bin" / binary_name()).is_file():
				found.append(version)

	if not found:
		return None

	newest = max(found, key=release_key)

	return cache / newest / "bin" / binary_name()


def ensure_mongod(major=DEFAULT_VERSION, environ=None):
	"""Path to a mongod binary for `major`, downloading it the first time."""

	cache = domino_home(environ) / "mongodb"

	path = cached_mongod(cache, major)
	if path is not None:
		return path

	download = select_download(fetch_index(), major)
	if download["note"]:
		log(download["note"])

	folder = cache / download["version"]
	path = folder / "bin" / binary_name()

	# Another `domino run` may be downloading the same build
	with file_lock(cache / f"{download['version']}.lock"):

		if path.is_file():
			return path

		folder.mkdir(parents=True, exist_ok=True)
		archive = download_archive(download, folder)
		try:
			extract_mongod(archive, path)
		finally:
			archive.unlink()

	return path


def download_archive(download, folder):

	url = download["url"]
	archive = folder / url.rsplit("/", 1)[-1]

	if download.get("sha256"):
		algorithm, expected = "sha256", download["sha256"]
	elif download.get("sha1"):
		algorithm, expected = "sha1", download["sha1"]
	else:
		raise DevMongoError(f"No checksum for {url}")

	log(f"Downloading MongoDB {download['version']} ({download['target']}) from {url}")

	handle, temp = tempfile.mkstemp(dir=folder, prefix=archive.name, suffix=".part")
	try:
		with os.fdopen(handle, "wb") as out, urllib.request.urlopen(url, timeout=60) as response:
			digest = copy_with_progress(response, out, int(response.headers.get("Content-Length") or 0), algorithm)

		check_digest(digest, expected, url)
		os.replace(temp, archive)
	except BaseException:
		Path(temp).unlink(missing_ok=True)
		raise

	return archive


def copy_with_progress(source, out, total, algorithm):

	digest = hashlib.new(algorithm)
	done = 0
	shown = -1

	while True:
		chunk = source.read(1 << 20)
		if not chunk:
			break
		out.write(chunk)
		digest.update(chunk)
		done += len(chunk)

		if total:
			percent = done * 100 // total
			if percent != shown:
				shown = percent
				print(f"\rdomino: downloading MongoDB... {percent}%", end="", file=sys.stderr, flush=True)

	if total:
		print(file=sys.stderr, flush=True)

	return digest.hexdigest()


def check_digest(actual, expected, url):

	if actual.lower() != expected.lower():
		raise DevMongoError(f"Checksum mismatch for {url}: expected {expected}, got {actual}")


def extract_mongod(archive, path):

	name = path.name
	path.parent.mkdir(parents=True, exist_ok=True)
	handle, temp = tempfile.mkstemp(dir=path.parent, prefix=name, suffix=".part")

	try:
		with os.fdopen(handle, "wb") as out:
			if archive.name.endswith(".zip"):
				with zipfile.ZipFile(archive) as bundle:
					member = find_member(bundle.namelist(), name, archive)
					with bundle.open(member) as source:
						shutil.copyfileobj(source, out)
			else:
				with tarfile.open(archive, "r:*") as bundle:
					member = find_member(bundle.getnames(), name, archive)
					shutil.copyfileobj(bundle.extractfile(member), out)

		os.chmod(temp, 0o755)
		os.replace(temp, path)
	except BaseException:
		Path(temp).unlink(missing_ok=True)
		raise


def find_member(names, binary, archive):

	for member in names:
		if member.endswith("/bin/" + binary):
			return member

	raise DevMongoError(f"{archive.name} has no bin/{binary}")


@contextmanager
def file_lock(path):

	path.parent.mkdir(parents=True, exist_ok=True)

	with open(path, "a+b") as handle:
		if os.name == "nt":
			import msvcrt
			handle.seek(0)
			while True:
				try:
					msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
					break
				except OSError:
					# LK_LOCK gives up after ten seconds; a download takes longer
					continue
		else:
			import fcntl
			fcntl.flock(handle, fcntl.LOCK_EX)

		try:
			yield
		finally:
			if os.name == "nt":
				handle.seek(0)
				msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
			else:
				fcntl.flock(handle, fcntl.LOCK_UN)


# Running mongod


def port_free(port):

	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
		# mongod sets SO_REUSEADDR, so connections left in TIME_WAIT by its last run don't
		# block it. On Windows the option means something else (sharing a listening port)
		if os.name != "nt":
			sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		try:
			sock.bind(("127.0.0.1", port))
		except OSError:
			return False

	return True


def free_port():

	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
		sock.bind(("127.0.0.1", 0))
		return sock.getsockname()[1]


def pick_port(preferred):

	if preferred and 0 < preferred < 65536 and port_free(preferred):
		return preferred

	return free_port()


def pid_alive(pid):

	if os.name == "nt":
		import ctypes
		process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
		if not process:
			return False
		code = ctypes.c_ulong()
		ctypes.windll.kernel32.GetExitCodeProcess(process, ctypes.byref(code))
		ctypes.windll.kernel32.CloseHandle(process)
		return code.value == 259  # STILL_ACTIVE

	try:
		os.kill(pid, 0)
	except ProcessLookupError:
		return False
	except PermissionError:
		return True

	return True


def require_pymongo():

	try:
		import pymongo
	except ImportError:
		raise DevMongoError("The development MongoDB needs pymongo: pip install pymongo") from None

	return pymongo


class DevMongo:
	"""A mongod serving one app folder's .domino/db."""


	def __init__(self, app_folder, port=None, major=DEFAULT_VERSION):

		self.folder = Path(app_folder).resolve() / ".domino"
		self.dbpath = self.folder / "db"
		self.logpath = self.folder / "mongod.log"
		self.statepath = self.folder / "mongod.json"
		self.dbname = database_name(app_folder)
		self.preferred_port = port
		self.major = major
		self.port = None
		self.process = None
		self.owned = False


	@property
	def url(self):

		return mongo_url(self.port, self.dbname)


	def start(self, timeout=60):

		pymongo = require_pymongo()

		self.dbpath.mkdir(parents=True, exist_ok=True)

		with file_lock(self.folder / "start.lock"):

			if self.reuse(pymongo):
				return self

			self.clear_stale_lock()

			mongod = ensure_mongod(self.major)
			self.port = pick_port(self.preferred_port)
			self.launch(mongod)
			self.owned = True
			stop_on_exit(self)

			self.statepath.write_text(json.dumps({"pid": self.process.pid, "port": self.port}), encoding="utf-8")

		self.wait_until_primary(pymongo, timeout)

		return self


	def reuse(self, pymongo):

		# A mongod left running for this app (by another `domino run`, or one that crashed)
		try:
			state = json.loads(self.statepath.read_text(encoding="utf-8"))
		except (OSError, ValueError):
			return False

		if not pid_alive(state.get("pid", 0)) or not self.reachable(pymongo, state.get("port")):
			self.statepath.unlink(missing_ok=True)
			return False

		self.port = state["port"]
		log(f"Reusing the MongoDB already running for this app (pid {state['pid']})")
		self.wait_until_primary(pymongo, 30)

		return True


	def clear_stale_lock(self):

		lock = self.dbpath / "mongod.lock"

		try:
			text = lock.read_text(encoding="utf-8").strip()
		except OSError:
			return

		if not text:
			return

		if text.isdigit() and pid_alive(int(text)):
			raise DevMongoError(f"Another mongod (pid {text}) is using {self.dbpath}; stop it or set mongo.url")

		# Left behind by a mongod that didn't shut down cleanly
		lock.unlink()


	def launch(self, mongod):

		command = [
			str(mongod),
			"--dbpath", str(self.dbpath),
			"--bind_ip", "127.0.0.1",
			"--port", str(self.port),
			"--replSet", REPLICA_SET,
			"--quiet",
		]

		options = {}
		if os.name == "nt":
			# Ctrl+C goes to the app; mongod is stopped by stop()
			options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
		else:
			options["start_new_session"] = True
			# The death signal follows the thread that started mongod, so only the main thread
			if sys.platform.startswith("linux") and threading.current_thread() is threading.main_thread():
				options["preexec_fn"] = die_with_parent

		with open(self.logpath, "ab") as logfile:
			self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=logfile, stderr=subprocess.STDOUT, **options)


	def reachable(self, pymongo, port):

		if not port:
			return False

		client = pymongo.MongoClient("127.0.0.1", port, directConnection=True, serverSelectionTimeoutMS=1000)
		try:
			client.admin.command("ping")
			return True
		except pymongo.errors.PyMongoError:
			return False
		finally:
			client.close()


	def wait_until_primary(self, pymongo, timeout):

		deadline = time.monotonic() + timeout
		client = pymongo.MongoClient("127.0.0.1", self.port, directConnection=True, serverSelectionTimeoutMS=500)

		try:
			while True:
				try:
					if self.ensure_replica_set(pymongo, client):
						return
				except pymongo.errors.PyMongoError:
					# Not accepting connections yet, or still electing itself
					pass

				if self.process is not None and self.process.poll() is not None:
					raise DevMongoError(f"mongod exited with code {self.process.returncode}; see {self.logpath}\n{self.log_tail()}")

				if time.monotonic() > deadline:
					raise DevMongoError(f"mongod didn't become ready within {timeout} seconds; see {self.logpath}")

				time.sleep(0.2)
		finally:
			client.close()


	def ensure_replica_set(self, pymongo, client):
		"""Initiate (or re-point) the single-node replica set change streams need.
		True once this node is primary."""

		host = f"127.0.0.1:{self.port}"

		try:
			config = client.admin.command("replSetGetConfig")["config"]
		except pymongo.errors.OperationFailure as error:
			# 94: NotYetInitialized
			if error.code != 94:
				raise
			try:
				client.admin.command("replSetInitiate", {"_id": REPLICA_SET, "members": [{"_id": 0, "host": host}]})
			except pymongo.errors.OperationFailure as error:
				# 23: AlreadyInitialized
				if error.code != 23:
					raise
			return False

		# The data folder remembers the port of the last run, which may have been different
		if config["members"][0]["host"] != host:
			config["members"] = [dict(config["members"][0], host=host)]
			config["version"] += 1
			client.admin.command("replSetReconfig", config, force=True)
			return False

		return bool(client.admin.command("hello").get("isWritablePrimary"))


	def log_tail(self, lines=20):

		try:
			text = self.logpath.read_text(encoding="utf-8", errors="replace")
		except OSError:
			return ""

		return "\n".join(text.splitlines()[-lines:])


	def stop(self, timeout=15):

		process = self.process
		if not self.owned or process is None:
			return

		self.owned = False

		if process.poll() is None:
			if os.name == "nt":
				shutdown_command(self.port)
			else:
				process.terminate()  # SIGTERM: mongod shuts down cleanly

			try:
				process.wait(timeout)
			except subprocess.TimeoutExpired:
				process.kill()
				process.wait()

		self.statepath.unlink(missing_ok=True)


def shutdown_command(port):

	# Windows has no SIGTERM; terminate() would kill mongod without a clean shutdown
	pymongo = require_pymongo()
	client = pymongo.MongoClient("127.0.0.1", port, directConnection=True, serverSelectionTimeoutMS=2000)
	try:
		client.admin.command("shutdown")
	except pymongo.errors.PyMongoError:
		# The connection drops as mongod exits
		pass
	finally:
		client.close()


def die_with_parent():

	# Linux: mongod gets SIGTERM if this process dies, even from SIGKILL, so it can't be orphaned
	import ctypes
	PR_SET_PDEATHSIG = 1
	ctypes.CDLL(None).prctl(PR_SET_PDEATHSIG, signal.SIGTERM)


_started = []


def stop_all():

	while _started:
		_started.pop().stop()


def stop_on_exit(mongo):

	if not _started:
		atexit.register(stop_all)
		install_signal_handlers()

	_started.append(mongo)


def install_signal_handlers():

	# SIGTERM and SIGHUP would otherwise end the process without running atexit.
	# SIGINT already raises KeyboardInterrupt, which does
	if threading.current_thread() is not threading.main_thread():
		return

	for name in ("SIGTERM", "SIGHUP"):
		number = getattr(signal, name, None)
		if number is not None and signal.getsignal(number) == signal.SIG_DFL:
			signal.signal(number, exit_on_signal)


def exit_on_signal(number, frame):

	sys.exit(128 + number)


def start(app_folder, port=None, major=DEFAULT_VERSION):
	"""Start (or reuse) the development MongoDB for `app_folder` and return its URL.
	It's stopped when this process exits."""

	mongo = DevMongo(app_folder, port, major).start()

	return mongo.url


def mongod_port(app_port):

	# Like Meteor: the app's port + 1 (5001 for 5000), or any free port
	if app_port and int(app_port) + 1 < 65536:
		return int(app_port) + 1

	return None
