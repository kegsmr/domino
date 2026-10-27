"""The app `domino create --minimal` makes, served by `domino run` and clicked in a real browser.
Skipped when Playwright isn't installed."""

import os
import re
import subprocess
import sys

import pytest

playwright = pytest.importorskip("playwright.sync_api")

import domino.cli as cli

from conftest import ROOT, wait_until


@pytest.fixture
def domino_run(tmp_path):
	"""`domino run <folder> --port 0` in a subprocess, with nothing set to turn MongoDB off."""

	processes = []

	def start(folder):

		log_path = tmp_path / "run.log"
		log = open(log_path, "w")
		# The tests' own MongoDB settings would hide whether the app turns it off itself
		env = {name: value for name, value in os.environ.items() if not name.startswith("DOMINO_") and name != "MONGO_URL"}
		env.update(PYTHONPATH=str(ROOT), DOMINO_HOME=str(tmp_path / "home"))
		command = "import sys; from domino.cli import main; sys.exit(main(sys.argv[1:]))"
		process = subprocess.Popen([sys.executable, "-c", command, "run", str(folder), "--port", "0"],
			stdout=log, stderr=subprocess.STDOUT, env=env, cwd=str(tmp_path), start_new_session=True)
		processes.append((process, log))

		def started():
			assert process.poll() is None, log_path.read_text()
			return re.search(r"App: http://127\.0\.0\.1:([1-9]\d*)/", log_path.read_text())

		wait_until(started, 60, "domino run didn't start")

		return f"http://127.0.0.1:{started().group(1)}/", log_path

	yield start

	for process, log in processes:
		if process.poll() is None:
			# The supervisor and the server process it started
			if os.name == "nt":
				subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
				process.wait()
			else:
				os.killpg(process.pid, 15)
				try:
					process.wait(15)
				except subprocess.TimeoutExpired:
					os.killpg(process.pid, 9)
					process.wait()
		log.close()


def test_minimal_app_runs_without_mongo_and_counts(tmp_path, domino_run):

	folder = tmp_path / "tiny"
	assert cli.main(["create", str(folder), "--minimal"]) == 0

	url, log_path = domino_run(folder)

	with playwright.sync_playwright() as p:
		browser = p.chromium.launch()
		try:
			page = browser.new_page()
			errors = []
			page.on("pageerror", lambda error: errors.append(str(error)))
			page.on("console", lambda message: message.type == "error" and errors.append(message.text))

			page.goto(url)
			page.wait_for_function("document.querySelector('[data-domino-ws]') && true")
			assert page.title() == "tiny"
			assert page.text_content("h1").strip() == "0"

			page.click("text=+1")
			page.click("text=+1")
			page.wait_for_function("document.querySelector('h1').textContent.trim() === '2'")

			# Another tab has its own count
			other = browser.new_page()
			other.goto(url)
			assert other.text_content("h1").strip() == "0"
			other.close()

			assert errors == []
		finally:
			browser.close()

	log = log_path.read_text()
	assert "MongoDB: disabled" in log
	assert not (tmp_path / "home" / "mongodb").exists()
	assert not (folder / ".domino" / "db").exists()
