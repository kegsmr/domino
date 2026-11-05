import domino.tags as t
from domino import State


OPTIONS = ["Newest", "Oldest", "Most liked"]


class SortMenu(t.div):

	open = State(False)
	choice = State("Newest")

	css = {
		"position": "relative",
		"display": "inline-block",
		"> button": {"padding": "0.4rem 0.9rem", "cursor": "pointer"},
		"ul": {"position": "absolute", "z_index": 1, "margin": "0.25rem 0 0", "padding": "0.25rem", "list_style": "none",
			"background": "var(--surface)", "border": "1px solid var(--line)", "border_radius": "6px", "min_width": "100%",
			"box_shadow": "0 4px 12px rgba(0, 0, 0, 0.15)"},
		"li button": {"width": "100%", "text_align": "left", "border": 0, "background": "none", "padding": "0.35rem 0.6rem", "cursor": "pointer", "white_space": "nowrap"},
		"li button:hover": {"background": "var(--line)"},
		"li button[aria-checked=true]::after": {"content": "' ✓'", "color": "var(--accent)"},
	}


	def render(self):

		children = [
			t.button(aria_haspopup="true", aria_expanded="true" if self.open else "false", on_click=self.toggle) [
				f"Sort: {self.choice} ▾"
			]
		]

		# The options and their buttons exist only while the menu is open
		if self.open:
			children.append(t.ul(role="menu") [[
				t.li() [
					t.button(role="menuitemradio", aria_checked="true" if option == self.choice else "false",
						on_click=(self.pick, option)) [
						option
					]
				]
				for option in OPTIONS
			]])

		return children


	def toggle(self):

		self.open = not self.open


	def pick(self, option):

		self.choice = option
		self.open = False
