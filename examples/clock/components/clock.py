import threading
import time

import domino.tags as t


# Nothing to mark: this module calls clock.refresh(), so pages showing it keep a channel open
class Clock(t.div):

	def render(self):

		return [
			t.p() [
				f"Server time: {time.strftime('%H:%M:%S')}"
			]
		]


# One clock shared by every page, so one refresh() updates them all
clock = Clock()


def tick():

	while True:
		time.sleep(1)
		clock.refresh()


threading.Thread(target=tick, daemon=True).start()
