import sys
import threading
import time

sys.path.append("")

import domino.tags as t
from domino import Domino
from domino.components import Document


app = Domino(__name__)


class Clock(t.div):

	# Pages showing a live component keep a stream open for refresh()
	live = True


	def render(self):

		self([
			t.p() [
				f"Server time: {time.strftime('%H:%M:%S')}"
			]
		])


# One clock shared by every page, so one refresh() updates them all
clock = Clock()


def tick():

	while True:
		time.sleep(1)
		clock.refresh()


threading.Thread(target=tick, daemon=True).start()


@app.route("/")
def index():

	return Document(title="Clock") [
		t.h1() [
			"Clock"
		],
		clock
	]


if __name__ == "__main__":
	app.run(debug=True)
