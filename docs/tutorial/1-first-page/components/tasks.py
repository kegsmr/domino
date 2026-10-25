from domino import Component, State
import domino.tags as t


# A component is a class; Component renders as a <div> (tag = "section" would pick another)
class Tasks(Component):

	# Each Tasks on a page has its own list; changing it re-renders the component
	items = State(["Read the tutorial", "Build something"])


	def render(self):

		return [
			t.ul [[
				t.li [
					item
				]
				for item in self.items
			]],
			t.button(on_click=self.add) [
				"Add a task"
			],
			t.p [
				f"{len(self.items)} tasks"
			]
		]


	# Runs on the server when the button is clicked; only what changed is sent back
	def add(self):

		self.items = self.items + [f"Task {len(self.items) + 1}"]
