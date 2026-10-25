import sys

sys.path.append("")

import domino.tags as t
from domino import Domino
from domino.components import Document


app = Domino(__name__)


LANGUAGES = [
	"Ada", "Assembly", "Bash", "C", "C#", "C++", "Clojure", "COBOL", "Crystal", "Dart",
	"Elixir", "Elm", "Erlang", "F#", "Fortran", "Go", "Groovy", "Haskell", "Java", "JavaScript",
	"Julia", "Kotlin", "Lisp", "Lua", "MATLAB", "Nim", "OCaml", "Pascal", "Perl", "PHP",
	"Prolog", "Python", "R", "Racket", "Ruby", "Rust", "Scala", "Scheme", "Smalltalk", "SQL",
	"Swift", "Tcl", "TypeScript", "V", "Zig",
]


class Search(t.div):


	def __init__(self, *args, **kwargs):

		super().__init__(*args, **kwargs)

		self.query = ""
		self.requests = 0


	def render(self):

		matches = [name for name in LANGUAGES if self.query.lower() in name.lower()]

		# The input is part of this component, yet it keeps focus, caret and anything
		# typed since the request was sent, because updates are patched in place
		self([
			box := t.input(type="search", placeholder="Search languages", value=self.query, autofocus=True),
			t.p() [
				f"{len(matches)} match(es), {self.requests} request(s) sent"
			],
			t.ul()([
				t.li() [
					name
				]
				for name in matches
			])
		])

		# Only sends once the user pauses for 250 ms
		box.bind("input", self.search, debounce=250)


	def search(self, event):

		self.query = event.value or ""
		self.requests += 1

		return self


@app.route("/")
def index():

	page = Document(title="Live search") [
		t.h1() [
			"Live search"
		],
		Search()
	]

	page.style("body", font_family="system-ui, sans-serif", max_width="28rem", margin="2rem auto")
	page.style("input", font="inherit", padding="0.5rem", width="100%", box_sizing="border-box")

	return page


if __name__ == "__main__":
	app.run(debug=True)
