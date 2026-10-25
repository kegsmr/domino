import sys
from pathlib import Path

# The repository root, so the example runs from any folder without installing Domino
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from domino import Domino


# Each file in pages/ is a page: pages/index.py is the page at /
app = Domino(__name__)


# A shared stylesheet, served at /style.css; pages reach it as current_app.stylesheet
stylesheet = app.style("/style.css")

stylesheet.style(
	"h1",
	color="#333",
	font_size="2.5rem",
	text_align="center",
	margin_bottom="10px",
)

stylesheet.style(
	"p",
	color="#666",
	font_size="1.2rem",
	text_align="center",
	line_height="1.5",
)

stylesheet.style(
	"a",
	color="#007BFF",
	text_decoration="none",
	font_weight="bold",
	display="block",
	text_align="center",
	margin_top="20px",
)


if __name__ == "__main__":
	app.run(debug=True)
