import domino.tags as t
from domino import State


TABS = [
	("Overview", "Every handler on this page only changes its component's own State, so Domino renders the states it leads to ahead of time."),
	("How", "The browser follows those states as you click, any number of clicks in a row, while the events still go to the server in order."),
	("Truth", "The server stays the source of truth: its answer to your last click confirms what you see, or puts it right."),
]


class Tabs(t.div):

	active = State(0)

	css = {
		"div": {"display": "flex", "gap": "0.25rem", "border_bottom": "1px solid var(--line)"},
		"button": {"border": 0, "background": "none", "padding": "0.5rem 1rem", "border_bottom": "2px solid transparent", "cursor": "pointer"},
		"button[aria-selected=true]": {"border_bottom_color": "var(--accent)", "color": "var(--accent)", "font_weight": 600},
		"p": {"padding": "0.25rem 0.25rem 0"},
	}


	def render(self):

		return [
			t.div(role="tablist") [[
				# (handler, argument): a click calls self.select(index), with this button's own index
				t.button(role="tab", aria_selected="true" if index == self.active else "false",
					on_click=(self.select, index)) [
					name
				]
				for index, (name, _) in enumerate(TABS)
			]],
			t.p(role="tabpanel") [
				TABS[self.active][1]
			]
		]


	# Only changes this component's State, so Domino can run it ahead of time
	def select(self, index):

		self.active = index
