"""The app the transport benchmark serves: python bench_app.py (wsgi|asgi) PORT.

wsgi serves it like before the async core (Werkzeug's threaded server: one thread per request,
each tab's Server-Sent Events stream holds one); asgi serves app.asgi with uvicorn.
"""

import sys

import domino.tags as t
from domino import Domino
from domino.components import Document


app = Domino(__name__)
app.config["DOMINO_MAX_PAGES"] = 100000


class Ticker(t.div):

	live = True


	def __init__(self, *args, **kwargs):

		super().__init__(*args, **kwargs)

		self.count = 0


	def render(self):

		self([
			t.p() [
				f"Ticks: {self.count}"
			]
		])


class Counter(t.div):


	def __init__(self, *args, **kwargs):

		super().__init__(*args, **kwargs)

		self.count = 0


	def render(self):

		self([
			t.p() [
				f"Count: {self.count}"
			],
			button := t.button() [
				"+"
			]
		])

		button.bind("click", self.increment)


	def increment(self):

		self.count += 1

		return self


# Shared by every page, so one refresh() fans out to all of them
ticker = Ticker()


@app.route("/")
def index():

	return Document() [
		ticker,
		Counter()
	]


@app.route("/bump")
def bump():

	ticker.count += 1
	ticker.refresh()

	return "ok"


if __name__ == "__main__":
	mode, port = sys.argv[1], int(sys.argv[2])

	if mode == "wsgi":
		import logging
		from werkzeug.serving import make_server
		# A log line per request would slow it down and flood the output
		logging.getLogger("werkzeug").setLevel(logging.WARNING)
		make_server("127.0.0.1", port, app, threaded=True).serve_forever()
	else:
		import uvicorn
		uvicorn.run(app.asgi, host="127.0.0.1", port=port, log_level="warning", backlog=4096)
