import domino.tags as t
from domino import Domino, State
from domino._core import Style
from domino import Document


class Card(t.div):

	css = {
		"": {"padding": "1rem"},
		"h3": {"margin": 0},
		":hover": {"box_shadow": "0 2px 8px gray"},
		"& + &": {"margin_top": "1rem"},
		"@media (max-width: 600px)": {"padding": ".5rem"},
	}


class Panel(Card):

	css = {"border": "1px solid"}


class PlainPanel(Card):
	pass


class Badge(t.span):

	css = """
	/* the component itself */
	& { color: red; display: -webkit-box; display: flex }
	b, i { font-weight: 600 }
	:hover { content: "a;b{c}" }
	"""


def render(element):

	# Without the indentation, so CSS can be compared on one line
	return element._render(indent="").replace("\t", "")


def head(html):

	return html.split("<head>")[1].split("</head>")[0]


def test_class_css_is_written_once_for_many_instances():

	html = render(Document()([Card() [t.h3() [str(i)]] for i in range(50)]))

	assert html.count(".Card {padding: 1rem") == 1
	assert html.count("<style") == 1
	assert '<style data-domino-css="Card">' in head(html)
	# No per-instance rules
	assert "#" not in head(html)


def test_selectors_are_scoped_to_the_component_class():

	css = render(Document() [Card()])

	assert ".Card {padding: 1rem;}" in css
	assert ".Card h3 {margin: 0;}" in css
	assert ".Card:hover {box-shadow: 0 2px 8px gray;}" in css
	assert ".Card + .Card {margin-top: 1rem;}" in css
	assert "@media (max-width: 600px) {.Card {padding: .5rem;}}" in css


def test_nested_selectors_pseudo_elements_and_at_rules():

	stylesheet = Style()
	stylesheet.style(".field", {
		"input, :is(a, b)": {"color": "red"},
		"::after": {"content": "'*'"},
		"[disabled]": {"opacity": 0.5},
		"> label": {"display": "block"},
		"&.wide, &:focus-within": {"width": "100%"},
		"@supports (display: grid)": {"display": "grid", "@media print": {"display": "block"}},
		"@keyframes pulse": {"from": {"opacity": 0}, "to": {"opacity": 1}},
	})

	css = stylesheet.compute().inner()

	assert ".field input, .field:is(a, b) {" in css
	assert ".field::after {" in css
	assert ".field[disabled] {" in css
	assert ".field > label {" in css
	assert ".field.wide, .field:focus-within {" in css
	assert "@supports (display: grid) {\n\t.field {\n\t\tdisplay: grid;" in css
	assert "\t@media print {\n\t\t.field {" in css
	# Keyframe selectors aren't scoped
	assert "@keyframes pulse {\n\tfrom {\n\t\topacity: 0;" in css


def test_subclasses_keep_the_base_css_and_add_their_own():

	html = render(Document() [Panel(), PlainPanel(), Card()])
	css = head(html)

	assert css.count(".Card {padding: 1rem") == 1
	assert css.count(".Panel {") == 1
	# Base first, so the subclass wins where they overlap
	assert css.index(".Card {padding: 1rem") < css.index(".Panel {")
	assert "PlainPanel" not in css


def test_raw_css_strings_are_scoped_like_dicts():

	css = render(Document() [Badge()])

	assert ".Badge {color: red;display: -webkit-box;display: flex;}" in css
	assert ".Badge b, .Badge i {font-weight: 600;}" in css
	assert '.Badge:hover {content: "a;b{c}";}' in css
	assert "the component itself" not in css


def test_rules_added_during_render_apply():

	class Box(t.div):

		def render(self):

			page.style(".Box", color="red")
			return ["hi"]

	page = Document() [Box()]

	assert ".Box {color: red;}" in head(render(page))


def test_rules_added_after_compute_apply_on_custom_pages():

	stylesheet = Style()

	class Page(t.html):

		def init(self):

			self([head := t.head(), t.body() [Box()]])
			stylesheet.compute(head)

	class Box(t.div):

		def render(self):

			stylesheet.style("p", color="blue")
			return ["hi"]

	assert "p {color: blue;}" in head(render(Page()))


def test_component_css_goes_in_any_head_before_its_stylesheets():

	page = t.html() [
		t.head() [
			t.title() ["x"],
			t.link(rel="stylesheet", href="/style.css"),
		],
		t.body() [
			Card()
		]
	]

	html = head(render(page))

	assert html.index('<style data-domino-css="Card">') < html.index("<link")


def test_component_css_comes_first_without_a_head():

	html = render(t.div() [Card(), Card()])

	assert html.startswith('<style data-domino-css="Card">')
	assert html.count("<style") == 1


def test_css_is_not_an_html_attribute():

	assert " css=" not in render(Card())


def test_event_response_carries_css_of_new_components_once():

	app = Domino(__name__)

	class Cards(t.div):

		shown = State(0)
		optimistic = False  # predictions would put Card's CSS in the page already


		def render(self):

			return [t.button(on_click=self.more) ["More"]] + [Card() for _ in range(self.shown)]


		def more(self):

			self.shown += 1

	@app.route("/")
	def index():

		return Document() [Cards()]

	client = app.test_client()
	html = client.get("/").get_data(as_text=True)
	assert ".Card" not in html

	page_id = html.split('data-domino-page="')[1].split('"')[0]
	event_id = html.split('data-event-id="')[1].split('"')[0]

	def click():

		return client.post("/_domino/events", json={"page_id": page_id, "event_id": event_id}).get_json()

	first = click()
	second = click()

	assert [name for name, _ in first["css"]] == ["Card"]
	assert ".Card {" in first["css"][0][1]
	assert "<style" not in first["html"]
	assert "css" not in second


def test_page_css_is_not_sent_again_in_event_responses():

	app = Domino(__name__)

	class Cards(t.div):

		def render(self):

			return [t.button(on_click=self.noop) ["Again"], Card()]


		def noop(self):

			pass

	@app.route("/")
	def index():

		return Document() [Cards()]

	client = app.test_client()
	html = client.get("/").get_data(as_text=True)
	page_id = html.split('data-domino-page="')[1].split('"')[0]
	event_id = html.split('data-event-id="')[1].split('"')[0]

	response = client.post("/_domino/events", json={"page_id": page_id, "event_id": event_id}).get_json()

	assert "Card" in response["html"]
	assert "css" not in response


def test_pushed_updates_carry_new_css_once():

	app = Domino(__name__)

	class Live(t.div):

		live = True
		shown = False


		def render(self):

			if self.shown:
				return [Badge()]
			return ["nothing yet"]

	live = Live()

	@app.route("/")
	def index():

		return Document() [live]

	client = app.test_client()
	html = client.get("/").get_data(as_text=True)
	page = app.page_store.pages[html.split('data-domino-page="')[1].split('"')[0]]
	page.open_stream()

	live.shown = True
	live.refresh()
	live.refresh()
	(update,) = page.pull(page.stream, 0)

	# The second refresh replaced the first, keeping the CSS the first one carried
	assert [name for name, _ in update["css"]] == ["Badge"]

	live.refresh()
	(update,) = page.pull(page.stream, 0)
	assert "css" not in update


def test_style_keeps_hover_and_element_rules():

	stylesheet = Style()
	stylesheet.style("a", color="blue", hover={"color": "red"})
	stylesheet.style("a", hover={"text_decoration": "underline"})

	css = stylesheet.compute().inner()

	assert "a {\n\tcolor: blue;\n}\na:hover {\n\tcolor: red;\n\ttext-decoration: underline;\n}" == css

	box = t.div()
	stylesheet.style(box, {":focus": {"outline": "none"}}, color="red")
	html = render(box)
	selector = Style.id_selector(box.id())
	assert f"{selector} {{color: red;}}" in html
	assert f"{selector}:focus {{outline: none;}}" in html


def test_none_values_are_left_out():

	assert Style().style("p", color=None, margin=0).compute().inner() == "p {\n\tmargin: 0;\n}"


def test_css_variables():

	css = Style().style(":root", __brand_color="teal", **{"--raw_name": "1px"}).compute().inner()

	assert "--brand-color: teal;" in css
	assert "--raw_name: 1px;" in css


def test_theme_sets_variables_with_a_dark_variant():

	page = Document().theme(surface="#fff", text_color="#111", dark={"surface": "#111"})

	css = head(render(page))

	# With a dark variant, the browser draws its own controls dark too
	assert ":root {--surface: #fff;--text-color: #111;color-scheme: light dark;}" in css
	assert "@media (prefers-color-scheme: dark) {:root {--surface: #111;}}" in css

	# Without one, the page stays light whatever the system prefers
	assert "color-scheme" not in head(render(Document().theme(surface="#fff")))


def test_values_cannot_close_the_style_element():

	class Evil(t.div):

		css = {"content": "'</style><script>alert(1)</script>'"}

	page = Document() [Evil()]
	page.style("p", font_family="</STYLE><b>")
	box = t.p()
	Style().style(box, color="</style>")

	html = render(page) + render(box)

	assert "</style><script>" not in html
	assert "</STYLE>" not in html
	assert html.count("</style>") == 3
	assert "<\\/style>" in html
