import sys

sys.path.append("")

from domino import Domino
import domino.tags as t


# Initialize the Domino app
app = Domino(__name__)


# Create a shared stylesheet
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


# Define a container class for styling
class container(t.div):

	def init(self):
		
		# Apply styles to the container
		stylesheet.style(
			self,
			font_family="Arial, sans-serif",
			max_width="800px",
			margin="0 auto",
			padding="20px",
			background_color="#f9f9f9",
			border_radius="10px",
			box_shadow="0 4px 6px rgba(0, 0, 0, 0.1)",
		)


# Define the HTML page
class HelloWorld(t.html):

	lang="en"

	def init(self):
		
		# Page content
		title = "Hello World!"
		subtitle = "Welcome to the world of Domino-based web development."
		url = "www.example.com"

		self([
			head := t.head() [
				t.title() [
					title
				]
			],
			t.body() [
				container() [
					t.h1() [
						title
					],
					t.p() [
						subtitle
					],
					t.a(href=f"https://{url}", target="_blank") [
						"Visit Example"
					]
				]
			]
		])

		# Inject computed stylesheet into head
		stylesheet.link(head)


# Route for the main page
@app.route("/")
def index():
	return HelloWorld()


# Run the app and generate the HTML
if __name__ == "__main__":
	app.run(debug=True)