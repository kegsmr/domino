from domino import State
from domino.components import Document
import domino.tags as t


# Logic in Python, markup in index.html next to this file: <component name="Counter"> there
class Counter(t.div):

	# This component's own data, one per open tab. Changing it re-renders this at once
	count = State(0)


	def increment(self):

		self.count += 1


# This file is the page at /
def page():

	return Document(title="minimal") [
		Counter()
	]
