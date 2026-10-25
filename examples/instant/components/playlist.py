import domino.tags as t
from domino import State


SONGS = [
	{"title": "So What", "year": 1959, "liked": True},
	{"title": "Naima", "year": 1960, "liked": False},
	{"title": "Maiden Voyage", "year": 1965, "liked": True},
	{"title": "Footprints", "year": 1966, "liked": False},
	{"title": "Blue in Green", "year": 1959, "liked": True},
]

SORTS = [("title", "Title"), ("year", "Year"), ("liked", "Liked first")]


class Playlist(t.div):

	sort = State("title")
	liked_only = State(False)
	compact = State(False)

	css = {
		".controls": {"display": "flex", "flex_wrap": "wrap", "gap": "1rem", "align_items": "center"},
		"select": {"font": "inherit", "padding": "0.2rem"},
		"ol": {"padding_left": "1.5rem"},
		"ol.compact li": {"display": "inline", "margin_right": "0.75rem"},
		".year": {"color": "var(--muted)"},
	}


	def render(self):

		songs = [song for song in SONGS if song["liked"] or not self.liked_only]
		if self.sort == "liked":
			songs = sorted(songs, key=lambda song: not song["liked"])
		else:
			songs = sorted(songs, key=lambda song: song[self.sort])

		return [
			t.div(class_="controls") [
				t.label() [
					"Sort by ",
					# Each option's value is known, so each choice is rendered ahead
					t.select(on_change=self.sort_by)([
						t.option(value=value, selected=value == self.sort) [label]
						for value, label in SORTS
					])
				],
				t.label() [
					t.input(type="checkbox", checked=self.liked_only, on_change=self.show_liked),
					" Liked only"
				],
				t.label() [
					t.input(type="checkbox", checked=self.compact, on_change=self.make_compact),
					" Compact"
				],
			],
			t.ol(class_="compact" if self.compact else None)([
				t.li() [
					f"{'♥ ' if song['liked'] else ''}{song['title']} ",
					t.span(class_="year") [str(song["year"])]
				]
				for song in songs
			])
		]


	# event.value of a <select> is one of its options, and of a checkbox True or False
	def sort_by(self, event):

		self.sort = event.value


	def show_liked(self, event):

		self.liked_only = event.value


	def make_compact(self, event):

		self.compact = event.value
