import reflex as rx


class CounterState(rx.State):
	count: int = 0

	@rx.event
	def increment(self):
		self.count += 1


def counter() -> rx.Component:
	return rx.box(
		rx.button("+1", id="inc", on_click=CounterState.increment),
		rx.text(CounterState.count, id="count", as_="span"),
	)
