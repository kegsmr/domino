import sys

sys.path.append("")

from domino import Domino


dom = Domino()

class text:
	__style__ = "font-family: arial;"
	style = "font-family: arial;"

@dom.element("html")
class document:

	@dom.element("head")
	class head:
		pass

	@dom.element("body")
	class body:
		
		@dom.element("h1", "Hello world!")
		class heading(text):
			pass

		@dom.element("p")
		class subtitle(text):
			__inner__ = "This is an HTML document made with Domino!"

		@dom.element("a")
		class link(text):
			href = "www.example.com"
			__inner__  = href


if __name__ == "__main__":
	with open("test.html", "w") as file:
		file.write(dom.render())