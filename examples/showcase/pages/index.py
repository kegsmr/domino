from domino import State
import domino.tags as t
from domino import Core


# Define reusable components. Each one's `css` is scoped to its class (.Navbar a, ...)
# and written into the page's <head> once, however many times the component is shown
class Navbar(t.div):

	css = {
		"display": "flex",
		"justify_content": "space-between",
		"align_items": "center",
		"background_color": "#333",
		"color": "#fff",
		"padding": "15px 30px",
		"position": "sticky",
		"top": "0",
		"z_index": "1000",
		"box_shadow": "0 2px 4px rgba(0, 0, 0, 0.1)",
		"> div": {"display": "flex", "gap": "20px"},
		"a": {
			"color": "#fff",
			"text_decoration": "none",
			"font_weight": "600",
			":hover": {"color": "#1E90FF"},
		},
	}

	links = [
		("Home", "#home"),
		("Features", "#features"),
		("Gallery", "#gallery"),
		("Contact", "#contact"),
	]

	def render(self):
		return [
			t.h1 ["Domino Showcase"],
			t.div [[t.a(href=href) [text] for text, href in self.links]],
		]


class HeroSection(t.section):

	css = {
		"display": "flex",
		"flex_direction": "column",
		"align_items": "center",
		"justify_content": "center",
		"text_align": "center",
		"height": "90vh",
		"background_image": "linear-gradient(135deg, #1E3C72, #2A5298 50%, #1E90FF)",
		"color": "#fff",
		"padding": "0 20px",
		"h1": {"font_size": "3.5rem", "margin_bottom": "15px", "text_shadow": "2px 2px 4px rgba(0, 0, 0, 0.5)"},
		"p": {"font_size": "1.2rem", "margin_bottom": "25px", "text_shadow": "1px 1px 2px rgba(0, 0, 0, 0.5)"},
		"a": {
			"background_color": "#1E90FF",
			"color": "#fff",
			"padding": "12px 25px",
			"border_radius": "8px",
			"text_decoration": "none",
			"font_weight": "600",
			"transition": "background-color 0.3s",
			":hover": {"background_color": "#0056b3"},
		},
	}

	attrs = {"id": "home"}

	def render(self):
		return [
			t.h1 ["Welcome to Domino"],
			t.p ["Build web pages with ease and elegance."],
			t.a(href="#features") ["Learn More"],
		]


class FeatureCard(t.div):

	css = {
		"padding": "25px",
		"background_color": "#fff",
		"border_radius": "12px",
		"box_shadow": "0 4px 6px rgba(0, 0, 0, 0.1)",
		"h3": {"font_size": "1.5rem", "margin_bottom": "15px", "color": "#333"},
		"p": {"color": "#555", "line_height": "1.6"},
	}


class FeaturesSection(t.section):

	css = {
		"padding": "60px 20px",
		"background_color": "#f4f4f4",
		"text_align": "center",
		"> div": {
			"display": "grid",
			"grid_template_columns": "repeat(auto-fit, minmax(250px, 1fr))",
			"gap": "30px",
		},
	}

	attrs = {"id": "features"}

	features = [
		("Simplicity", "Write minimal code to generate clean HTML and CSS."),
		("Flexibility", "Style elements dynamically with reusable styles."),
		("Modularity", "Build reusable components for efficient development."),
	]

	def render(self):
		return [
			t.h2 ["Features"],
			t.div [[FeatureCard [t.h3 [title], t.p [description]] for title, description in self.features]],
		]


class Tile(t.div):

	css = {
		"aspect_ratio": "1",
		"display": "flex",
		"align_items": "center",
		"justify_content": "center",
		"color": "#fff",
		"font_weight": "600",
		"border_radius": "10px",
		"box_shadow": "0 2px 4px rgba(0, 0, 0, 0.1)",
	}


class GallerySection(t.section):

	css = {
		"padding": "60px 20px",
		"text_align": "center",
		"> div": {
			"display": "grid",
			"grid_template_columns": "repeat(auto-fit, minmax(250px, 1fr))",
			"gap": "20px",
		},
	}

	attrs = {"id": "gallery"}

	def render(self):
		# Generated tiles instead of images, so the example needs no network. Only the
		# color differs per tile, so it's an inline style; the rest is Tile's css
		return [
			t.h2 ["Gallery"],
			t.div [[
				Tile(style={
					"background_image": f"linear-gradient(135deg, hsl({i * 50}, 70%, 55%), hsl({i * 50 + 40}, 70%, 40%))"
				}) [f"Image {i}"]
				for i in range(1, 7)
			]],
		]


class ContactSection(t.section):

	css = {
		"padding": "60px 20px",
		"background_color": "#f9f9f9",
		"text_align": "center",
		"h2": {"margin_bottom": "30px"},
		"form": {
			"display": "flex",
			"flex_direction": "column",
			"gap": "20px",
			"max_width": "400px",
			"margin": "0 auto",
		},
		"input, textarea": {
			"padding": "12px",
			"border": "1px solid #ccc",
			"border_radius": "8px",
			"font": "inherit",
		},
		"button": {
			"background_color": "#1E90FF",
			"color": "#fff",
			"padding": "12px",
			"border": "none",
			"border_radius": "8px",
			"font_weight": "600",
			"cursor": "pointer",
			":hover": {"background_color": "#0056b3"},
		},
	}

	attrs = {"id": "contact"}

	sender = State(None)


	def render(self):

		if self.sender:
			return [t.h2 ["Contact Us"], t.p [f"Thanks, {self.sender}! We'll be in touch."]]

		return [
			t.h2 ["Contact Us"],
			t.form(on_submit=self.send) [
				t.input(type="text", name="name", placeholder="Your Name", required=True),
				t.input(type="email", name="email", placeholder="Your Email"),
				t.textarea(name="message", placeholder="Your Message", rows="4"),
				t.button(type="submit") ["Send Message"],
			],
		]


	def send(self, event):

		self.sender = event.form.get("name") or "friend"


class Footer(t.footer):

	css = {
		"text_align": "center",
		"padding": "30px",
		"background_color": "#333",
		"color": "#fff",
		"margin_top": "50px",
	}

	def render(self):
		return [t.p ["© 2025 Domino Showcase. All rights reserved."]]


# A page can be a component class named Page: each visit gets a new one, so each
# visitor's contact form has its own state
class Page(t.html):

	# Rules for the whole page; the page is a component too
	css = {
		"body": {"font_family": "'Segoe UI', system-ui, sans-serif", "margin": "0"},
		"h2": {"font_size": "2.5rem", "margin_bottom": "40px", "color": "#333"},
	}

	def render(self):

		return [
			t.head [
				t.title ["Domino Showcase"],
				# Domino's client script, needed for events (Document adds this itself)
				Core()
			],
			t.body [
				Navbar(),
				HeroSection(),
				FeaturesSection(),
				GallerySection(),
				ContactSection(),
				Footer(),
			]
		]

