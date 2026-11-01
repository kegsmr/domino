import domino.tags as t

from components.code import Code


class Prose(t.div):
	"""Text written in Markdown: the guide's sections and the tutorial's prose."""

	css = {
		"line_height": "1.7",
		"h2": {
			"font_size": "1.45rem", "line_height": "1.3", "letter_spacing": "-0.015em",
			"margin": "3rem 0 0.75rem", "padding_top": "1.5rem", "border_top": "1px solid var(--line)",
			"scroll_margin_top": "5rem",
		},
		"h3": {"font_size": "1.1rem", "margin": "2rem 0 0.5rem", "scroll_margin_top": "5rem"},
		"h2 .anchor, h3 .anchor": {"margin_left": "0.4rem", "color": "var(--muted)", "text_decoration": "none", "opacity": "0"},
		"h2:hover .anchor, h3:hover .anchor, .anchor:focus-visible": {"opacity": "1"},
		"p, ul, ol, table": {"margin": "0 0 1rem"},
		"ul, ol": {"padding_left": "1.25rem"},
		"li": {"margin": "0.3rem 0"},
		"li::marker": {"color": "var(--muted)"},
		"a": {"color": "var(--accent)", "text_decoration": "underline", "text_decoration_color": "var(--accent-soft)", "text_underline_offset": "2px"},
		"a:hover": {"text_decoration_color": "currentColor"},
		"code": {
			"font": "0.86em var(--mono)", "background": "var(--inline-code)", "padding": "0.12em 0.35em", "border_radius": "4px",
			"overflow_wrap": "anywhere",
		},
		"strong": {"font_weight": "600"},
		"table": {"border_collapse": "collapse", "width": "100%", "font_size": "0.92rem", "display": "block", "overflow_x": "auto"},
		"th, td": {"text_align": "left", "padding": "0.5rem 0.75rem", "border_bottom": "1px solid var(--line)", "vertical_align": "top"},
		"blockquote": {"margin": "1rem 0", "padding": "0.25rem 1rem", "border_left": "3px solid var(--accent)", "color": "var(--muted)"},
	}


def blocks(parts, demo=None):
	"""Components for rendered Markdown parts (see markup.render and content.step_parts):
	text in Prose blocks, code in Code blocks. `demo(part)` makes the parts that aren't either."""

	shown = []
	for part in parts:
		kind = part[0]
		if kind == "html":
			shown.append(Prose() [part[1]])
		elif kind == "code":
			shown.append(Code(part[2], part[1]))
		else:
			shown.append(demo(part))

	return shown
