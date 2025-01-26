import sys

sys.path.append("")
from domino import Domino, Style
import domino.tags as t
from domino.bootstrap import BootstrapCSS, JQuery, PopperJS, BootstrapJS  # Import Bootstrap components

# Initialize the Domino app
app = Domino(__name__)

# Create a shared stylesheet
stylesheet = Style()

# Define reusable components
class Navbar(t.div):
    def inner(self):
        BootstrapCSS(self)  # Add Bootstrap CSS
        JQuery(self)  # Add JQuery
        PopperJS(self)  # Add Popper.js
        BootstrapJS(self)  # Add Bootstrap JS
        
        stylesheet.style(
            self,
            display="flex",
            justify_content="space-between",
            align_items="center",
            background_color="#333",
            color="#fff",
            padding="15px 30px",
            position="sticky",
            top="0",
            z_index="1000",
            box_shadow="0 2px 4px rgba(0, 0, 0, 0.1)",
        )
        t.h1(self, "Domino Showcase")
        nav_links = t.div(self)
        stylesheet.style(nav_links, display="flex", gap="20px")

        links = [
            ("Home", "#home"),
            ("Features", "#features"),
            ("Gallery", "#gallery"),
            ("Contact", "#contact"),
        ]
        for link_text, link_href in links:
            link = t.a(nav_links, link_text, href=link_href)
            stylesheet.style(
                link,
                color="#fff",
                text_decoration="none",
                font_weight="600",
                hover={"color": "#1E90FF"},
            )

class HeroSection(t.section):
    def inner(self):
        stylesheet.style(
            self,
            display="flex",
            flex_direction="column",
            align_items="center",
            justify_content="center",
            text_align="center",
            height="90vh",
            background_image="url('https://via.placeholder.com/1920x1080')",
            background_size="cover",
            background_position="center",
            color="#fff",
            padding="0 20px",
        )
        t.h1(self, "Welcome to Domino")
        stylesheet.style("h1", font_size="3.5rem", margin_bottom="15px", text_shadow="2px 2px 4px rgba(0, 0, 0, 0.5)")
        t.p(self, "Build web pages with ease and elegance.")
        stylesheet.style("p", font_size="1.2rem", margin_bottom="25px", text_shadow="1px 1px 2px rgba(0, 0, 0, 0.5)")
        cta = t.a(self, "Learn More", href="#features")
        stylesheet.style(
            cta,
            background_color="#1E90FF",
            color="#fff",
            padding="12px 25px",
            border_radius="8px",
            text_decoration="none",
            font_weight="600",
            transition="background-color 0.3s",
            hover={"background_color": "#0056b3"},
        )

class FeaturesSection(t.section):
    def inner(self):
        self.__attributes__["id"] = "features"
        stylesheet.style(
            self,
            padding="60px 20px",
            background_color="#f4f4f4",
            text_align="center",
        )
        t.h2(self, "Features")
        stylesheet.style("h2", font_size="2.5rem", margin_bottom="40px", color="#333")

        features = [
            ("Simplicity", "Write minimal code to generate clean HTML and CSS."),
            ("Flexibility", "Style elements dynamically with reusable styles."),
            ("Modularity", "Build reusable components for efficient development."),
        ]

        grid = t.div(self)
        stylesheet.style(
            grid,
            display="grid",
            grid_template_columns="repeat(auto-fit, minmax(300px, 1fr))",
            gap="30px",
        )

        for title, desc in features:
            card = t.div(grid)
            stylesheet.style(
                card,
                padding="25px",
                background_color="#fff",
                border_radius="12px",
                box_shadow="0 4px 6px rgba(0, 0, 0, 0.1)",
            )
            t.h3(card, title)
            stylesheet.style("h3", font_size="1.5rem", margin_bottom="15px", color="#333")
            t.p(card, desc)
            stylesheet.style("p", color="#555", line_height="1.6")

class Footer(t.footer):
    def inner(self):
        stylesheet.style(
            self,
            text_align="center",
            padding="30px",
            background_color="#333",
            color="#fff",
            margin_top="50px",
        )
        t.p(self, "© 2025 Domino Showcase. All rights reserved.")

class ShowcasePage(t.html):
    def inner(self):
        head = t.head(self)
        t.title(head, "Domino Showcase")

        body = t.body(self)
        stylesheet.style(body, font_family="Segoe UI")

        # Insert the Bootstrap components
        Navbar(body)
        HeroSection(body)
        FeaturesSection(body)
        Footer(body)

        stylesheet.compute(head)

@app.route("/")
def index():
    return page.render()

if __name__ == "__main__":
    page = ShowcasePage()
    with open("output.html", "w") as file:
        file.write(page.render())
    app.run(debug=True)