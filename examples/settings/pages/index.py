from flask import current_app

import domino.tags as t
from domino.components import Document


# This file is the page at /. Pages read the app's settings through current_app
def page():

	settings = current_app.settings

	return Document(title=settings.site_name) [
		t.h1() [
			settings.site_name
		],
		t.p() [
			f"Pages expire after {current_app.config['DOMINO_PAGE_TTL']} seconds of inactivity (domino.page_ttl)."
		],
		t.p(id="greeting"),
		# Only the "public" block reaches the browser, as Domino.settings
		t.script() [
			"const greeting = document.getElementById('greeting');\n"
			"greeting.textContent = Domino.settings.greeting;\n"
			"greeting.style.color = Domino.settings.theme_color;"
		]
	]
