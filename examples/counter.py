import sys

sys.path.append("")
from domino import Domino, request, jsonify
import domino.tags as t


app = Domino(__name__)


class CounterComponent(t.div):
	
	def inner(self):
	
		# Declare state variables
		count, set_count = self.state(0)

		# Display the current count
		t.h1(self, f"Current Count: {count}")

		# Increment button
		increment_button = t.button(self, "Increment")
		increment_button.bind("click", lambda: set_count(count + 1))

		# Decrement button
		decrement_button = t.button(self, "Decrement")
		decrement_button.bind("click", lambda: set_count(count - 1))


@app.route("/")
def index():

	return home


if __name__ == "__main__":

	home = t.html()
	head = t.head(home)
	body = t.body(home)

	CounterComponent(body)

	app.run(debug=True)