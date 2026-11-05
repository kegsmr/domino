from flask import request

import domino.tags as t
from domino import Document

from components.navbar import NavBar


TITLES = {
	"/": "Domino + Tailwind",
	"/pricing": "Pricing · Domino + Tailwind",
}


# Wraps every page. Nothing here but Tailwind classes: dark: variants follow the visitor's system
# setting, md: and lg: ones the width of the window
def layout(content):

	page = Document(title=TITLES.get(request.path, "Domino + Tailwind"))
	page.body.configure(class_="min-h-screen bg-white font-sans text-slate-900 antialiased dark:bg-slate-950 dark:text-slate-100")

	return page [
		NavBar(),
		t.main() [
			content
		],
		t.footer(class_="border-t border-slate-200 dark:border-slate-800") [
			t.p(class_="mx-auto max-w-6xl px-6 py-8 text-sm text-slate-500 dark:text-slate-400") [
				"Styled only with Tailwind CSS classes, built by Domino with no Node, no config and no build step."
			]
		]
	]
