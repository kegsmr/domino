import domino.tags as t
from domino import State


# A component's `css` is scoped to its class: "" (or plain properties) is the component
# itself, "h3" its descendants, ":hover" and "::before" attach to it, "&" stands for it.
# It goes into the page's <head> once, however many cards are shown.
class Card(t.article):

	css = {
		"padding": "1rem 1.25rem",
		"border_radius": "10px",
		"background": "var(--surface)",
		"box_shadow": "0 1px 3px rgba(0, 0, 0, 0.12)",
		"transition": "box-shadow 0.2s",
		":hover": {"box_shadow": "0 4px 12px rgba(0, 0, 0, 0.18)"},
		"h3": {"margin": "0 0 0.25rem"},
		"p": {"margin": 0, "color": "var(--muted)"},
		"@media (max-width: 600px)": {"padding": "0.75rem"},
	}


# Subclasses keep their base class's styles and add their own
class Highlight(Card):

	css = {
		"border_left": "4px solid var(--accent)",
		"h3::before": {"content": "'★ '", "color": "var(--accent)"},
	}


# Plain CSS works too, scoped the same way
class Pill(t.span):

	css = """
	& {
		display: inline-block;
		padding: 0.1rem 0.6rem;
		border-radius: 999px;
		background: var(--accent);
		color: white;
		font-size: 0.8rem;
	}
	"""


class Board(t.div):

	cards = State(3)
	optimistic = False  # show the server's answer, so the new card's CSS arrives with it

	css = {
		"display": "grid",
		"gap": "1rem",
		"grid_template_columns": "repeat(auto-fill, minmax(14rem, 1fr))",
		"> button": {"grid_column": "1 / -1", "justify_self": "start", "font": "inherit", "padding": "0.4rem 1rem"},
	}


	def render(self):

		cards = []
		for number in range(1, self.cards + 1):
			card = Card
			if number % 4 == 0:
				card = Highlight
			cards.append(card() [
				t.h3() [f"Card {number}"],
				t.p() ["Styled once per page, not once per card."]
			])

		# The first Highlight appears with the fourth card; its CSS comes with that response
		return [t.button(on_click=self.add) ["Add a card"]] + cards


	def add(self):

		self.cards += 1
