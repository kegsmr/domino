import sys

sys.path.append("")

from domino import Domino, Style
import domino.tags as t


# Initialize the Domino app
app = Domino(__name__)

# Create a shared stylesheet
stylesheet = app.style("/style.css")


# Define a container class for styling
class container(t.div):

	def inner(self):
		
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

	def inner(self):
		
		# Page content
		title = "Hello World!"
		subtitle = "Welcome to the world of Domino-based web development."
		url = "www.example.com"

		# Add head content
		head = t.head(self)
		t.title(head, title)

		# Add body content
		body = t.body(self)

		# Create a container for content
		div = container(body)

		# Header
		t.h1(div, title)
		stylesheet.style(
			"h1",
			color="#333",
			font_size="2.5rem",
			text_align="center",
			margin_bottom="10px",
		)

		# Subtitle paragraph
		t.p(div, subtitle)
		stylesheet.style(
			"p",
			color="#666",
			font_size="1.2rem",
			text_align="center",
			line_height="1.5",
		)

		# Link
		t.a(div, "Visit Example", href=f"https://{url}", target="_blank")
		stylesheet.style(
			"a",
			color="#007BFF",
			text_decoration="none",
			font_weight="bold",
			display="block",
			text_align="center",
			margin_top="20px",
		)

		# Inject computed stylesheet into head
		stylesheet.link(head)


# Route for the main page
@app.route("/")
def index():
	
	return home


# Run the app and generate the HTML
if __name__ == "__main__":
	
	home = HelloWorld()

	# Write the HTML to a file for testing
	with open("output.html", "w") as file:
		file.write(home.render())

	# Start the Domino app
	app.run(debug=True)