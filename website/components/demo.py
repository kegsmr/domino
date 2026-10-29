import domino.tags as t


class Demo(t.figure):
	"""A live component running on a docs page, framed like a little browser window."""

	css = {
		"margin": "1.5rem 0",
		"border": "1px solid var(--line)",
		"border_radius": "12px",
		"background": "var(--surface)",
		"box_shadow": "var(--shadow)",
		"overflow": "hidden",
		"figcaption": {
			"display": "flex", "align_items": "center", "gap": "0.5rem", "flex_wrap": "wrap",
			"padding": "0.55rem 1rem", "border_bottom": "1px solid var(--line)", "background": "var(--surface-2)",
			"font_size": "0.8rem", "color": "var(--muted)",
		},
		".live": {
			"display": "inline-flex", "align_items": "center", "gap": "0.35rem",
			"font_weight": "600", "color": "var(--text)", "letter_spacing": "0.02em",
		},
		".live::before": {
			"content": "''", "width": "0.5rem", "height": "0.5rem", "border_radius": "50%",
			"background": "var(--live)", "box_shadow": "0 0 0 3px var(--live-soft)",
		},
		"code": {"font": "0.78rem var(--mono)"},
		# The tutorial's components use --accent behind white text
		".stage": {"padding": "1.25rem 1.25rem 1.5rem", "__accent": "var(--demo-accent)"},
		# Plain controls, so steps without styles of their own still look tidy here
		".stage button, .stage input:not([type=checkbox])": {"font": "inherit"},
		".stage h1": {"font_size": "1.4rem", "margin": "0 0 0.75rem"},
	}


	def __init__(self, component, note=None, **attributes):

		self.demo_component = component
		self.demo_note = note

		super().__init__(**attributes)


	def render(self):

		return [
			t.figcaption() [
				t.span(class_="live") [
					"Live"
				],
				t.span() [
					self.demo_note or "The real component, running on this page"
				]
			],
			t.div(class_="stage") [
				self.demo_component
			]
		]
