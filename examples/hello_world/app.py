import sys


sys.path.append("")

from domino import Domino, Element, Style
import domino.tags as t


app = Domino(__name__)

stylesheet = Style()


class container(t.div):

	def inner(self):

		stylesheet.style(self, font_family="arial")


class HelloWorld(t.html):


	def inner(self):

		title = "Hello World!"
		subtitle = "This is an HTML document made with Domino!"
		url = "www.example.com"

		head = t.head(self)
		
		t.title(head, title)

		body = t.body(self)

		div = container(body)

		t.h1(div, title)
		t.p(div, subtitle)

		t.a(div, url, href=f"https://{url}")

		stylesheet.compute(head)


@app.route("/")
def index():

	return home.render()


if __name__ == "__main__":

	home = HelloWorld()

	with open("test.html", "w") as file:
		file.write(home.render())

	app.run(debug=True)