import domino.tags as t
from domino import State


class Stepper(t.div):

	value = State(0)

	css = {
		"display": "flex",
		"align_items": "center",
		"gap": "0.75rem",
		"button": {"width": "2.25rem", "height": "2.25rem", "font_size": "1.25rem", "cursor": "pointer"},
		"output": {"min_width": "1.5rem", "text_align": "center", "font_size": "1.5rem", "font_variant_numeric": "tabular-nums"},
	}


	def render(self):

		return [
			t.button(aria_label="Fewer", disabled=self.value == 0, on_click=self.decrement) [
				"−"
			],
			t.output() [
				str(self.value)
			],
			t.button(aria_label="More", disabled=self.value == 5, on_click=self.increment) [
				"+"
			],
			t.span() [
				"guests (0 to 5)"
			]
		]


	# Bounded, so there are six states: the browser gets all of them
	def increment(self):

		self.value = min(5, self.value + 1)


	def decrement(self):

		self.value = max(0, self.value - 1)
