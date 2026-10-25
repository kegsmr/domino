from markupsafe import Markup

import domino.tags as t

import markup


class Code(t.figure):
	"""A highlighted code block, with its file name (if any) and a copy button."""

	css = {
		"position": "relative",
		"margin": "1.25rem 0",
		"border": "1px solid var(--line)",
		"border_radius": "10px",
		"background": "var(--code-bg)",
		"overflow": "hidden",
		"figcaption": {
			"display": "flex", "align_items": "center", "gap": "0.5rem",
			"padding": "0.45rem 0.6rem 0.45rem 1rem", "border_bottom": "1px solid var(--line)",
			"font": "500 0.8rem/1.4 var(--mono)", "color": "var(--muted)",
		},
		"figcaption span": {"flex": "1", "overflow": "hidden", "text_overflow": "ellipsis", "white_space": "nowrap"},
		"pre": {
			"margin": 0, "padding": "0.9rem 1rem", "overflow_x": "auto",
			"font": "0.84rem/1.6 var(--mono)", "tab_size": "4", "color": "var(--code-text)",
		},
		".copy": {
			"font": "500 0.75rem/1 var(--sans)", "color": "var(--muted)", "background": "var(--surface)",
			"border": "1px solid var(--line)", "border_radius": "6px", "padding": "0.3rem 0.55rem", "cursor": "pointer",
		},
		".copy:hover": {"color": "var(--text)"},
		".copy[data-copied]": {"color": "var(--accent)"},
		# Without a file name, the button floats over the code's corner and shows on hover
		"> .copy": {"position": "absolute", "top": "0.5rem", "right": "0.5rem", "opacity": "0", "transition": "opacity .15s"},
		":hover > .copy, > .copy:focus-visible": {"opacity": "1"},
		"@media (hover: none)": {"> .copy": {"opacity": "1"}},
		# Pygments' token classes
		".c, .c1, .cm, .ch, .cs, .cp": {"color": "var(--tok-comment)", "font_style": "italic"},
		".k, .kn, .kc, .kd, .kr, .kt, .ow, .nt": {"color": "var(--tok-keyword)"},
		".s, .s1, .s2, .sa, .sb, .sd, .se, .si, .sh, .dl, .sx, .na + .o + .s": {"color": "var(--tok-string)"},
		".nf, .fm, .nd, .na": {"color": "var(--tok-function)"},
		".nc, .nn, .bp, .nb": {"color": "var(--tok-name)"},
		".mi, .mf, .m, .il, .mh, .kc": {"color": "var(--tok-number)"},
		".gp, .go": {"color": "var(--muted)", "user_select": "none"},
	}


	def __init__(self, source, language="python", caption=None, **attributes):

		self.code_source = source
		self.code_language = language
		self.code_caption = caption

		super().__init__(**attributes)


	def render(self):

		copy = t.button(type="button", class_="copy", data_copy=True, aria_label="Copy code") [
			"Copy"
		]

		pre = Markup("<pre><code>{}</code></pre>").format(markup.highlight(self.code_source, self.code_language))

		if self.code_caption:
			return [
				t.figcaption() [
					t.span() [
						self.code_caption
					],
					copy
				],
				pre
			]

		return [copy, pre]
