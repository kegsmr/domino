from domino import Document

from components.layout import Layout


# Wraps every page in a Document with the navigation
def layout(content):

	page = Document(title="Developer tools") [
		Layout(content)
	]

	page.style("body", font_family="system-ui, sans-serif", max_width="42rem", margin="2rem auto", padding="0 1rem", line_height="1.5")
	page.style("button", font="inherit", padding=".3rem .8rem")
	page.style("section", border="1px solid #ddd", border_radius="8px", padding=".25rem 1rem 1rem", margin="1rem 0")

	return page
