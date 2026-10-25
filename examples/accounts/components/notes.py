import time

import domino.tags as t
from domino import accounts

from data import notes


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
