import sys

sys.path.append("")

import domino.tags as t
from domino import Domino
from domino.components import Document


# Reads settings.json, then settings.local.json, from this folder; DOMINO_* environment
# variables override both (e.g. DOMINO_PUBLIC__GREETING=Hi)
app = Domino(__name__)


@app.route("/")
def index():

	return Document(title=app.settings.site_name) [
		t.h1() [
			app.settings.site_name
		],
		t.p() [
			f"Pages expire after {app.config['DOMINO_PAGE_TTL']} seconds of inactivity (domino.page_ttl)."
		],
		t.p(id="greeting"),
		# Only the "public" block reaches the browser, as Domino.settings
		t.script() [
			"const greeting = document.getElementById('greeting');\n"
			"greeting.textContent = Domino.settings.greeting;\n"
			"greeting.style.color = Domino.settings.theme_color;"
		]
	]


if __name__ == "__main__":
	app.run(debug=True)
