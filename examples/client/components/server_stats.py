from domino import State

from components.stats import TextStats


# The same component run the usual way, on the server: every keystroke is a round trip. Turn on
# the latency simulator (`Domino.enableLatencySim(300)` in the console) to feel the difference.
class ServerTextStats(TextStats):

	client = False

	text = State("Type here. Every keystroke goes to the server and back.")
