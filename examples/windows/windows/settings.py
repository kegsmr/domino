from domino import Window

from data import theme


class Settings(Window):

	tab = "general"


	def dark(self):

		return theme.value == "dark"


	def pick(self, event):

		theme.value = event.value
