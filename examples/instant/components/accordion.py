import domino.tags as t
from domino import State


SECTIONS = [
	("What runs in the browser?", "Nothing you write: the server renders each state once and the browser swaps them in."),
	("What if the server disagrees?", "Its answer wins. If something changed on the server meanwhile, the page shows what it says."),
	("Which handlers qualify?", "Ones that only set the component's own State with plain expressions. Anything else waits for the server."),
]


class Accordion(t.div):

	open = State(None)  # the index of the open section, if any

	css = {
		"section": {"border_bottom": "1px solid var(--line)"},
		"button": {"width": "100%", "text_align": "left", "border": 0, "background": "none", "padding": "0.6rem 0.25rem", "cursor": "pointer", "font_weight": 600},
		"button::before": {"content": "'▸ '", "color": "var(--muted)"},
		"button[aria-expanded=true]::before": {"content": "'▾ '"},
		"p": {"margin": "0 0 0.75rem 1.25rem", "color": "var(--muted)"},
	}


	def render(self):

		sections = []
		for index, (question, answer) in enumerate(SECTIONS):
			opened = index == self.open
			sections.append(t.section() [
				t.button(aria_expanded="true" if opened else "false", on_click=lambda event, index=index: self.toggle(index)) [
					question
				],
				t.p() [answer] if opened else ""
			])

		return sections


	def toggle(self, index):

		self.open = None if self.open == index else index
