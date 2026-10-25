from flask import current_app

import domino.tags as t


# A component's own styles, scoped to its class (.container) and added to the page once
class container(t.div):

	css = {
		"font_family": "Arial, sans-serif",
		"max_width": "800px",
		"margin": "0 auto",
		"padding": "20px",
		"background_color": "#f9f9f9",
		"border_radius": "10px",
		"box_shadow": "0 4px 6px rgba(0, 0, 0, 0.1)",
	}


# Define the HTML page; a whole <html> page is used as it is, without layouts
class HelloWorld(t.html):

	# HTML attributes of the element itself; other class attributes are plain Python
	attrs = {"lang": "en"}

	title = "Hello World!"
	subtitle = "Welcome to the world of Domino-based web development."
	url = "www.example.com"

	def render(self):

		return [
			t.head() [
				t.title() [
					self.title
				],
				# Link the app's stylesheet, served at /style.css
				current_app.stylesheet.link()
			],
			t.body() [
				container() [
					t.h1() [
						self.title
					],
					t.p() [
						self.subtitle
					],
					t.a(href=f"https://{self.url}", target="_blank") [
						"Visit Example"
					]
				]
			]
		]


# This file is the page at /
def page():

	return HelloWorld()
