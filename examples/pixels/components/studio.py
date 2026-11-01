import domino.tags as t
from domino import State

from data import pixels

SIZE = 24
COLORS = ["#ff595e", "#ffca3a", "#8ac926", "#1982c4", "#6a4c93", "#f5f5f5", "#222222"]
BLANK = "#1b1b1b"


class Studio(t.div):
	"""The palette and the canvas: Python decides, the HTML draws."""

	color = State(COLORS[0])

	def render(self):
		return [
			Palette(current=self.color, on_pick=self.pick, on_clear=self.clear),
			Canvas(color=self.color),
			Stats(),
		]

	def pick(self, color):
		self.color = color

	def clear(self):
		pixels.remove()


class Palette(t.div):

	current = COLORS[0]
	on_pick = None
	on_clear = None

	def colors(self):
		return COLORS

	def is_picked(self, color):
		return color == self.current

	def pick(self, color):
		self.on_pick(color)

	def clear(self):
		self.on_clear()


class Canvas(t.div):

	color = COLORS[0]

	def cells(self):
		# Reading the collection here makes every open canvas repaint when anyone paints
		painted = {pixel["_id"]: pixel["color"] for pixel in pixels.find()}
		return [(f"{x}-{y}", painted.get(f"{x}-{y}", BLANK)) for y in range(SIZE) for x in range(SIZE)]

	def paint(self, key):
		if not pixels.update({"_id": key}, {"$set": {"color": self.color}}):
			pixels.insert({"_id": key, "color": self.color})


class Stats(t.p):

	def painted(self):
		return pixels.count()

	def total(self):
		return SIZE * SIZE
