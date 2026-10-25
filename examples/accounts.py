import sys
import time

sys.path.append("")

import domino.tags as t
from domino import Collection, Domino, accounts
from domino.components import Document


# Logins are kept in a session cookie signed with the secret_key setting. In debug mode
# (as below) a random key is made up if there's none, so logins last until a restart;
# set your own in settings.local.json or DOMINO_SECRET_KEY
app = Domino(__name__)


# Each note has an owner; the private page shows only the signed-in user's notes
notes = Collection("notes")


class Notes(t.div):


	def render(self):

		# Reactive: logging out (here or in the menu) re-renders this
		user = accounts.current_user()
		if user is None:
			return [
				t.p() [
					"You've logged out. ",
					t.a(href="/login?next=/private") ["Log in"],
					" to see your notes."
				]
			]

		mine = notes.find({"owner": user["_id"]}, sort=[("created", -1)])

		return [
			t.p() [f"Only you can see these, {user.get('name') or user.get('email')}."],
			t.form(on_submit=self.add) [
				t.input(name="text", placeholder="A note", required=True, autocomplete="off"),
				t.button(type="submit") ["Add"]
			],
			t.ul()([
				t.li() [note["text"]] for note in mine
			])
		]


	def add(self, event):

		# The page's user, not anything the browser sent, decides whose note this is
		owner = accounts.user_id()
		text = str(event.form.get("text", "")).strip()[:500]
		if owner is None or not text:
			return

		notes.insert({"owner": owner, "text": text, "created": time.time()})


def layout(title, *content):

	page = Document(title=title) [
		t.header() [
			t.a(href="/") ["Home"],
			" ",
			t.a(href="/private") ["Private"],
			accounts.UserMenu()
		],
		t.main()([
			t.h1() [title],
			*content
		])
	]

	page.style("body", font_family="system-ui, sans-serif", max_width="32rem", margin="2rem auto", padding="0 1rem")
	page.style("header", display="flex", gap="1rem", align_items="center", border_bottom="1px solid #ddd", padding_bottom="0.75rem")
	page.style(".UserMenu", margin_left="auto", display="flex", gap="0.75rem", align_items="center")
	page.style("form", display="flex", flex_direction="column", gap="0.5rem", max_width="20rem")
	page.style(".Notes form", flex_direction="row")
	page.style("label", display="flex", flex_direction="column", gap="0.25rem")
	page.style("input", font="inherit", padding="0.4rem")
	page.style(".error", color="#b00020")

	return page


@app.route("/")
def index():

	return layout(
		"Accounts",
		t.p() [
			t.a(href="/signup?next=/private") ["Sign up"],
			", then add notes on the private page. They're only shown to you."
		]
	)


@app.route("/signup")
def signup():

	return layout("Sign up", accounts.SignupForm())


@app.route("/login")
def login():

	return layout("Log in", accounts.LoginForm())


@app.route("/private")
@accounts.login_required
def private():

	return layout("Private", Notes())


if __name__ == "__main__":
	app.run(debug=True, threaded=True)
