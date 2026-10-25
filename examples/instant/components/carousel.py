import domino.tags as t
from domino import State


SLIDES = [
	("Dawn", "linear-gradient(135deg, #fbc2eb, #a6c1ee)"),
	("Noon", "linear-gradient(135deg, #fddb92, #d1fdff)"),
	("Dusk", "linear-gradient(135deg, #f6d365, #fda085)"),
	("Night", "linear-gradient(135deg, #30cfd0, #330867)"),
]


class Carousel(t.div):

	index = State(0)

	css = {
		"figure": {"margin": 0, "height": "9rem", "border_radius": "10px", "display": "flex", "align_items": "flex-end", "padding": "0.75rem",
			"color": "white", "font_weight": 600, "text_shadow": "0 1px 3px rgba(0, 0, 0, 0.5)"},
		"nav": {"display": "flex", "align_items": "center", "gap": "0.5rem", "margin_top": "0.5rem"},
		"nav > button": {"cursor": "pointer"},
		".dot": {"width": "0.75rem", "height": "0.75rem", "padding": 0, "border_radius": "50%", "border": "1px solid var(--muted)", "background": "none"},
		".dot[aria-current=true]": {"background": "var(--accent)", "border_color": "var(--accent)"},
	}


	def render(self):

		name, background = SLIDES[self.index]
		count = len(SLIDES)

		return [
			t.figure(style={"background": background}) [
				f"{name} ({self.index + 1}/{count})"
			],
			t.nav()([
				# Each render works out where previous and next go, so they're plain values
				t.button(aria_label="Previous", on_click=lambda event, index=(self.index - 1) % count: self.show(index)) ["‹"],
				*[
					t.button(class_="dot", aria_label=slide, aria_current="true" if number == self.index else "false",
						on_click=lambda event, number=number: self.show(number))
					for number, (slide, _) in enumerate(SLIDES)
				],
				t.button(aria_label="Next", on_click=lambda event, index=(self.index + 1) % count: self.show(index)) ["›"],
			])
		]


	def show(self, index):

		self.index = index
