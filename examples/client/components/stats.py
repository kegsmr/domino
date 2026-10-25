# Live text statistics, recomputed on every keystroke. With `client = True` that happens in the
# browser; components/server_stats.py runs the very same class on the server, for comparison.

import domino.tags as t
from domino import State


class TextStats(t.div):

	client = True

	text = State("Type here. Every keystroke is counted in your browser, in Python, without asking the server.")

	css = {
		"textarea": {"width": "100%", "box_sizing": "border-box", "font": "inherit", "padding": "0.5rem"},
		"dl": {"display": "grid", "grid_template_columns": "auto 1fr", "gap": "0.1rem 1rem", "margin": "0.5rem 0 0"},
		"dt": {"color": "var(--muted)"},
		"dd": {"margin": 0, "font_variant_numeric": "tabular-nums"},
	}


	def render(self):

		words = self.text.split()
		sentences = len([part for part in self.text.replace("!", ".").replace("?", ".").split(".") if part.strip()])
		longest = max(words, key=len) if words else "–"

		return [
			t.textarea(rows=4, aria_label="Text to count", on_input=self.typed) [self.text],
			t.dl() [
				t.dt() ["Characters"], t.dd() [str(len(self.text))],
				t.dt() ["Words"], t.dd() [str(len(words))],
				t.dt() ["Sentences"], t.dd() [str(sentences)],
				t.dt() ["Longest word"], t.dd() [longest],
				t.dt() ["Reading time"], t.dd() [f"{max(1, round(len(words) / 4)) if words else 0} s"],
			],
		]


	def typed(self, event):

		self.text = event.value
