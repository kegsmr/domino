import domino.tags as t
from domino import open_window

from data import theme


class Toolbar(t.div):


	def current(self):

		return theme.value


	def audio(self):

		# Opens it with a value of its own (or Settings.open(tab="audio"))
		open_window("Settings", tab="audio")
