import domino.tags as t
from domino import State


LANGUAGES = [
	"Ada", "Assembly", "Bash", "C", "C#", "C++", "Clojure", "COBOL", "Crystal", "Dart",
	"Elixir", "Elm", "Erlang", "F#", "Fortran", "Go", "Groovy", "Haskell", "Java", "JavaScript",
	"Julia", "Kotlin", "Lisp", "Lua", "MATLAB", "Nim", "OCaml", "Pascal", "Perl", "PHP",
	"Prolog", "Python", "R", "Racket", "Ruby", "Rust", "Scala", "Scheme", "Smalltalk", "SQL",
	"Swift", "Tcl", "TypeScript", "V", "Zig",
]


class Search(t.div):

	query = State("")
	requests = State(0)


	def render(self):

		matches = [name for name in LANGUAGES if self.query.lower() in name.lower()]

		# The input is part of this component, yet it keeps focus, caret and anything
		# typed since the request was sent, because updates are patched in place.
		# debounce: only send once the user pauses for 250 ms
		return [
			t.input(type="search", placeholder="Search languages", value=self.query, autofocus=True, on_input=self.search, debounce=250),
			t.p() [
				f"{len(matches)} match(es), {self.requests} request(s) sent"
			],
			t.ul()([
				t.li() [
					name
				]
				for name in matches
			])
		]


	def search(self, event):

		self.query = event.value or ""
		self.requests += 1
