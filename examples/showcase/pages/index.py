from domino.components import Core
import domino.tags as t


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

	def init(self):
		t.h1(self, "Domino Showcase")
		nav_links = t.div(self)

		links = [
			("Home", "#home"),
			("Features", "#features"),
			("Gallery", "#gallery"),
			("Contact", "#contact"),
		]
		for link_text, link_href in links:
			t.a(nav_links, link_text, href=link_href)


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

	def init(self):
		self.id("home")
		t.h1(self, "Welcome to Domino")
		t.p(self, "Build web pages with ease and elegance.")
		t.a(self, "Learn More", href="#features")


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

	def init(self):
		self.__attributes__["id"] = "features"
		t.h2(self, "Features")

		features = [
			("Simplicity", "Write minimal code to generate clean HTML and CSS."),
			("Flexibility", "Style elements dynamically with reusable styles."),
			("Modularity", "Build reusable components for efficient development."),
		]

		grid = t.div(self)
		for title, desc in features:
			card = FeatureCard(grid)
			t.h3(card, title)
			t.p(card, desc)


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

	def init(self):
		self.__attributes__["id"] = "gallery"
		t.h2(self, "Gallery")

		gallery = t.div(self)

		# Generated tiles instead of images, so the example needs no network. Only the
		# color differs per tile, so it's an inline style; the rest is Tile's css
		for i in range(1, 7):
			Tile(gallery, f"Image {i}", style={
				"background_image": f"linear-gradient(135deg, hsl({i * 50}, 70%, 55%), hsl({i * 50 + 40}, 70%, 40%))"
			})


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

	def init(self):
		self.__attributes__["id"] = "contact"
		self.sender = None


	def render(self):

		# Rebuilt on every render, so start from no children
		self([])
		t.h2(self, "Contact Us")

		if self.sender:
			t.p(self, f"Thanks, {self.sender}! We'll be in touch.")
			return

		form = t.form(self)
		form.bind("submit", self.send)

		t.input(form, type="text", name="name", placeholder="Your Name", required=True)
		t.input(form, type="email", name="email", placeholder="Your Email")
		t.textarea(form, name="message", placeholder="Your Message", rows="4")
		t.button(form, "Send Message", type="submit")


	def send(self, event):

		self.sender = event.form.get("name") or "friend"

		return self


class Footer(t.footer):

	css = {
		"text_align": "center",
		"padding": "30px",
		"background_color": "#333",
		"color": "#fff",
		"margin_top": "50px",
	}

	def init(self):
		t.p(self, "© 2025 Domino Showcase. All rights reserved.")


# A page can be a component class named Page: each visit gets a new one, so each
# visitor's contact form has its own state
class Page(t.html):

	# Rules for the whole page; the page is a component too
	css = {
		"body": {"font_family": "'Segoe UI', system-ui, sans-serif", "margin": "0"},
		"h2": {"font_size": "2.5rem", "margin_bottom": "40px", "color": "#333"},
	}

	def init(self):

		head = t.head(self)
		t.title(head, "Domino Showcase")

		# Domino's client script, needed for events (Document adds this itself)
		head.add_children([Core()])

		body = t.body(self)

		Navbar(body)
		HeroSection(body)
		FeaturesSection(body)
		GallerySection(body)
		ContactSection(body)
		Footer(body)

