import domino.tags as t
from domino import State


QUESTIONS = [
	("Where does the markup go?", "In .html files: a component's is inside a tag named after its class."),
	("Where does the logic go?", "In Python: State, helpers the template reads, and event handlers."),
	("Why is it instant?", "toggle() only changes this component's State, so every state is shipped with the page."),
]


class Faq(t.div):

	open = State(None)
	questions = QUESTIONS


	def is_open(self, index):

		return self.open == index


	def expanded(self, index):

		# aria-expanded wants "true" or "false" (True alone would write the attribute without a value)
		return "true" if self.open == index else "false"


	def toggle(self, index):

		self.open = None if self.open == index else index
