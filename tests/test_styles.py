import domino.tags as t
from domino import Domino, Style


def test_element_styles_do_not_accumulate_in_shared_stylesheet():

	app = Domino(__name__)
	stylesheet = app.style("/style.css")
	stylesheet.style("h1", color="red")

	@app.route("/")
	def index():
		box = t.div() ["hi"]
		stylesheet.style(box, color="blue")
		return box

	client = app.test_client()
	for _ in range(100):
		html = client.get("/").get_data(as_text=True)

	assert list(stylesheet.styles) == ["h1"]
	assert "color: blue;" in html
	assert "#" not in client.get("/style.css").get_data(as_text=True)


def test_element_styles_render_with_the_element():

	stylesheet = Style()
	box = t.div() ["hi"]
	stylesheet.style(box, color="red", hover={"color": "blue"})

	html = box._render(indent="")

	assert html.startswith("<div")
	assert f"#{box.id()} {{" in html
	assert f"#{box.id()}:hover {{" in html


def test_void_element_styles_render_before_the_element():

	image = t.img(src="x.png")
	Style().style(image, width="10px")

	html = image._render(indent="")

	assert html.startswith("<style")
	assert html.index("width: 10px;") < html.index("<img")


def test_id_selectors_escape_leading_digits():

	assert Style.id_selector("81e4-abc") == "#\\38 1e4-abc"
	assert Style.id_selector("main") == "#main"
