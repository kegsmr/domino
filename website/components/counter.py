from domino import State
import domino.tags as t


class Counter(t.div):

	count = State(0)  # changing it re-renders the component

	css = {  # scoped to .Counter, written once per page
		"display": "flex", "gap": "1rem", "align_items": "center",
		"button": {"width": "2.5rem", "border_radius": "50%"},
		"output": {"font_size": "2rem", "font_weight": "700"},
	}

	def render(self):
		return [
			t.button(on_click=self.decrement) ["−"],
			t.output() [f"{self.count}"],
			t.button(on_click=self.increment) ["+"],
		]

	def increment(self):  # runs on the server, no JavaScript
		self.count += 1

	def decrement(self):
		self.count -= 1
