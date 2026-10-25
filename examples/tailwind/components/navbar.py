from flask import request

import domino.tags as t
from domino import State


LINKS = [
	("Features", "/#features"),
	("Pricing", "/pricing"),
	("Sign up", "/#signup"),
]


# A responsive navbar: links in a row from md: up, behind a menu button below that. The button
# toggles which classes the menu has; class names are written out in full, so Tailwind finds them
class NavBar(t.header):

	open = State(False)


	def render(self):

		return [
			t.nav(class_="mx-auto flex max-w-6xl items-center justify-between px-6 py-4") [
				t.a(href="/", class_="flex items-center gap-2 text-lg font-bold tracking-tight") [
					t.span(class_="grid size-8 place-items-center rounded-lg bg-indigo-600 text-sm text-white") ["D"],
					"Domino"
				],
				t.div(class_="hidden items-center gap-8 md:flex") [[
					self.link(text, href, "text-sm font-medium")
					for text, href in LINKS
				]],
				t.button(
					on_click=self.toggle,
					aria_expanded="true" if self.open else "false",
					aria_controls="mobile-menu",
					aria_label="Menu",
					class_="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium md:hidden dark:border-slate-700"
				) [
					"Close" if self.open else "Menu"
				]
			],
			t.div(id="mobile-menu", class_="border-t border-slate-200 px-6 py-3 md:hidden dark:border-slate-800 " + ("block" if self.open else "hidden")) [[
				self.link(text, href, "block rounded-lg px-3 py-2 font-medium hover:bg-slate-100 dark:hover:bg-slate-800")
				for text, href in LINKS
			]]
		]


	def link(self, text, href, classes):

		current = "page" if request.path == href else None

		# Two utilities for one property would leave which wins to the order of Tailwind's CSS
		if current:
			classes += " text-indigo-600 dark:text-indigo-400"
		else:
			classes += " text-slate-600 hover:text-indigo-600 dark:text-slate-300 dark:hover:text-indigo-400"

		return t.a(href=href, aria_current=current, class_=classes) [
			text
		]


	def toggle(self):

		self.open = not self.open
