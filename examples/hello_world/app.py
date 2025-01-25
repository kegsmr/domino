import sys


sys.path.append("")

from domino import Domino
import domino.tags as t


app = Domino(__name__)


class HelloWorld(t.html):


	def __init__(self):
	
		super().__init__()

		title = "Hello World!"
		subtitle = "This is an HTML document made with Domino!"
		url = "www.example.com"

		head = t.head(self)
		
		t.title(head, title)
		t.style(head)

		body = t.body(self)

		t.h1(body, title)
		t.p(body, subtitle)

		t.a(body, url, href=f"https://{url}")


@app.route("/")
def index():

	return home.render()


if __name__ == "__main__":

	home = HelloWorld()

	with open("test.html", "w") as file:
		file.write(home.render())

	app.run(debug=True)