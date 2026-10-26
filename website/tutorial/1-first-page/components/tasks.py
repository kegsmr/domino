import domino.tags as t
from domino import State


# A component is a class: it subclasses the tag it renders as (here a <div>)
class Tasks(t.div):

	# Each Tasks on a page has its own list; changing it re-renders the component
	items = State(["Read the tutorial", "Build something"])


	def render(self):

		return [
			t.ul()([
				t.li() [
					item
				]
				for item in self.items
			]),
			t.button(on_click=self.add) [
				"Add a task"
			],
			t.p() [
				f"{len(self.items)} tasks"
			]
		]


	# Runs on the server when the button is clicked; only what changed is sent back
	def add(self):

		self.items = self.items + [f"Task {len(self.items) + 1}"]
