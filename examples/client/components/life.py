# A client component: `client = True` runs it in the browser, in Python. This whole file is sent
# to the browser, so it only imports what exists there (domino.tags, State, math, random, time,
# json) and holds nothing secret. The server renders its first HTML, so the board shows before
# Python has loaded; from then on every click and every generation is computed in the browser,
# 30 times a second, without the server (it keeps going offline).

import time

import domino.tags as t
from domino import State


SIZE = 20
FPS = 30

# A glider and a small exploder, as indexes into the board
START = [row * SIZE + column for row, column in [(0, 1), (1, 2), (2, 0), (2, 1), (2, 2)] + [(8, 9), (8, 10), (8, 11), (9, 9), (9, 11), (10, 9), (10, 11), (11, 10), (12, 9), (12, 10), (12, 11)]]


def now():

	# MicroPython has ticks_ms(); CPython (rendering on the server) has time()
	return time.ticks_ms() if hasattr(time, "ticks_ms") else int(time.time() * 1000)


class Life(t.div):

	client = True

	cells = State([1 if index in START else 0 for index in range(SIZE * SIZE)])
	running = State(False)
	generation = State(0)
	fps = State(0)
	started = State(0)  # ms, when the frame count was last reset
	frames = State(0)

	css = {
		".board": {
			"display": "grid", "grid_template_columns": f"repeat({SIZE}, 1fr)", "gap": "1px",
			"width": "min(100%, 26rem)", "aspect_ratio": "1", "background": "var(--line)", "border": "1px solid var(--line)",
			"cursor": "pointer", "touch_action": "manipulation",
		},
		".board span": {"background": "var(--surface)"},
		".board span.on": {"background": "var(--accent)"},
		".controls": {"display": "flex", "gap": "0.5rem", "flex_wrap": "wrap", "margin": "0.75rem 0 0.25rem"},
		".status": {"color": "var(--muted)", "font_variant_numeric": "tabular-nums", "margin": 0},
	}


	def render(self):

		# The next generation, 1/FPS s after this render; rendering again schedules the one after
		if self.running:
			self.after(1000 // FPS, self.tick)

		alive = sum(self.cells)

		return [
			t.div(class_="board", role="grid", aria_label="Game of Life board")([
				t.span(class_="on" if cell else None, on_click=lambda event, index=index: self.toggle(index))
				for index, cell in enumerate(self.cells)
			]),
			t.p(class_="controls") [
				t.button(type="button", on_click=self.toggle_running) ["Pause" if self.running else "Start"],
				t.button(type="button", on_click=self.tick, disabled=self.running) ["Step"],
				t.button(type="button", on_click=self.randomize) ["Random"],
				t.button(type="button", on_click=self.clear) ["Clear"],
				t.button(type="button", class_="save", on_click=self.save) ["Save to server"],
			],
			t.p(class_="status", aria_live="off") [
				f"Generation {self.generation} · {alive} alive" + (f" · {self.fps} generations/s" if self.running else "")
			],
		]


	def toggle(self, index):

		cells = list(self.cells)
		cells[index] = 1 - cells[index]
		self.cells = cells


	def toggle_running(self):

		self.running = not self.running
		self.started = now()
		self.frames = 0


	def tick(self):

		cells = self.cells
		after = []
		for index in range(SIZE * SIZE):
			row, column = index // SIZE, index % SIZE
			up, down = (row - 1) % SIZE * SIZE, (row + 1) % SIZE * SIZE
			here = row * SIZE
			left, right = (column - 1) % SIZE, (column + 1) % SIZE
			neighbours = (
				cells[up + left] + cells[up + column] + cells[up + right]
				+ cells[here + left] + cells[here + right]
				+ cells[down + left] + cells[down + column] + cells[down + right]
			)
			after.append(1 if neighbours == 3 or (neighbours == 2 and cells[index]) else 0)

		self.cells = after
		self.generation += 1

		# Generations per second over the last second or so
		self.frames += 1
		elapsed = now() - self.started
		if elapsed >= 1000:
			self.fps = round(self.frames * 1000 / elapsed)
			self.started = now()
			self.frames = 0


	def randomize(self):

		import random
		self.cells = [1 if random.random() < 0.3 else 0 for _ in range(SIZE * SIZE)]
		self.generation = 0


	def clear(self):

		self.cells = [0] * (SIZE * SIZE)
		self.generation = 0
		self.running = False


	def save(self):

		# The server component around this one gave it on_save=...: the one round trip here
		self.emit("save", {"generation": self.generation, "alive": sum(self.cells), "cells": self.cells})
