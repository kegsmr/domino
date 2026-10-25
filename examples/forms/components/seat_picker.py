import domino.tags as t


class SeatCount(t.output):


	def init(self):

		self.seats = 1


	def render(self):

		return [
			f"{self.seats} seat(s)"
		]


class SeatPicker(t.div):
	"""A raw control without forms.Form: a range input whose change re-renders only the count."""


	def init(self):

		self.seat_count = SeatCount()


	def render(self):

		return [
			t.label() [
				"Seats ",
				t.input(type="range", name="seats", min=1, max=20, value=self.seat_count.seats, on_change=self.set_seats),
				" ",
				self.seat_count
			]
		]


	def set_seats(self, event):

		# The element's value arrives as event.value. Returning the count re-renders only it,
		# so nothing else on the page is touched
		self.seat_count.seats = int(event.value)

		return self.seat_count
