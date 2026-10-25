import domino.tags as t
from domino import State

from components.life import Life


# A server component with a client component inside: the board runs in the browser, and its
# "Save to server" button calls save() here, through the on_save= it was given. Re-rendering this
# component leaves the running board alone.
class Patterns(t.section):

	saved = State([])

	css = {
		"ol": {"padding_left": "1.25rem", "margin": "0.25rem 0"},
		".empty": {"color": "var(--muted)"},
	}


	def render(self):

		return [
			Life(on_save=self.save),
			t.h3() ["Saved on the server"],
			t.ol()([
				t.li() [f"Generation {pattern['generation']}: {pattern['alive']} cells alive"]
				for pattern in self.saved
			]) if self.saved else t.p(class_="empty") ["Nothing yet: press “Save to server”."],
		]


	def save(self, event):

		# event.value is what the client component sent with self.emit("save", ...); it comes
		# from the browser, so check it like any other input
		value = event.value if isinstance(event.value, dict) else {}
		cells = value.get("cells") if isinstance(value.get("cells"), list) else []
		self.saved = self.saved + [{"generation": int(value.get("generation") or 0), "alive": sum(1 for cell in cells if cell)}]
