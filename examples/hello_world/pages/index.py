from flask import current_app

import domino.tags as t


# Define a container class for styling
class container(t.div):

	def init(self):

		# Apply styles to the container
		current_app.stylesheet.style(
			self,
			font_family="Arial, sans-serif",
			max_width="800px",
			margin="0 auto",
			padding="20px",
			background_color="#f9f9f9",
			border_radius="10px",
			box_shadow="0 4px 6px rgba(0, 0, 0, 0.1)",
		)


# Define the HTML page; a whole <html> page is used as it is, without layouts
class HelloWorld(t.html):

	lang="en"

	def init(self):

		# Page content
		title = "Hello World!"
		subtitle = "Welcome to the world of Domino-based web development."
		url = "www.example.com"

		self([
			t.head() [
				t.title() [
					title
				],
				# Link the app's stylesheet, served at /style.css
				current_app.stylesheet.link()
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


# This file is the page at /
def page():

	return HelloWorld()
