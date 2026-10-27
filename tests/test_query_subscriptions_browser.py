"""Per-query subscriptions in a real browser: a change reaches the other tabs showing the
documents it touches, and only them. Skipped when Playwright isn't installed."""

import threading
import uuid

import pytest

playwright = pytest.importorskip("playwright.sync_api")

from werkzeug.serving import make_server

import domino.tags as t
from domino import Collection, Domino
from domino.components import Document

from test_query_subscriptions import watched


def make_app(tasks, renders):

	class Tasks(t.ul):

		owner = None

		def render(self):
			renders[self.owner] = renders.get(self.owner, 0) + 1
			return [
				t.li() [
					task["text"],
					t.button(on_click=lambda event, key=task["_id"]: self.finish(key)) ["Done"]
				]
				for task in tasks.find({"owner": self.owner, "done": False}, sort="text")
			]

		def finish(self, key):
			tasks.update({"_id": key}, {"$set": {"done": True}})

	app = Domino(__name__)

	@app.route("/<owner>")
	def index(owner):
		return Document(title=owner) [Tasks(owner=owner)]

	return app


@pytest.fixture
def served():

	servers = []

	def start(app):
		server = make_server("127.0.0.1", 0, app, threaded=True)
		threading.Thread(target=server.serve_forever, daemon=True).start()
		servers.append(server)
		return f"http://127.0.0.1:{server.server_port}/"

	yield start

	for server in servers:
		server.shutdown()


@pytest.fixture(params=["memory", pytest.param("mongo", marks=pytest.mark.mongo)])
def tasks(request):

	if request.param == "memory":
		return Collection()

	return watched(Collection(f"test_{uuid.uuid4().hex[:8]}"))


def test_a_change_updates_the_tabs_it_affects_and_only_them(tasks, served):

	for owner, text in [("ada", "Write notes"), ("ada", "Run tests"), ("bob", "Review")]:
		tasks.insert({"owner": owner, "text": text, "done": False})
	renders = {}
	url = served(make_app(tasks, renders))

	with playwright.sync_playwright() as p:
		browser = p.chromium.launch()
		try:
			errors = []
			pages = {}
			for name, owner in [("ada", "ada"), ("ada2", "ada"), ("bob", "bob")]:
				page = pages[name] = browser.new_page()
				page.on("pageerror", lambda error: errors.append(str(error)))
				page.on("console", lambda message: message.type == "error" and errors.append(message.text))
				page.goto(url + owner)
				page.wait_for_function("document.querySelector('[data-domino-page]') && window.Domino && true")
			# Each tab's own update stream is open before the change
			for page in pages.values():
				page.wait_for_timeout(300)
			before = dict(renders)

			pages["ada"].click("li:has-text('Run tests') button")

			for name in ["ada", "ada2"]:
				pages[name].wait_for_function("document.querySelectorAll('li').length === 1")
				assert pages[name].text_content("li").strip().startswith("Write notes")
			pages["bob"].wait_for_timeout(500)

			assert pages["bob"].text_content("li").strip().startswith("Review")
			assert renders["ada"] > before["ada"]
			assert renders["bob"] == before["bob"]
			assert errors == []
		finally:
			browser.close()
