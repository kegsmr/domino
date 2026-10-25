import domino.tags as t
from domino import accounts
from domino import Document


# Wraps every page: the navigation with the user menu, which updates when you log in or out
def layout(content):

	page = Document(title="Accounts") [
		t.header() [
			t.a(href="/") ["Home"],
			" ",
			t.a(href="/private") ["Private"],
			" ",
			t.a(href="/members") ["Members"],
			accounts.UserMenu()
		],
		t.main() [
			content
		]
	]

	page.style("body", font_family="system-ui, sans-serif", max_width="32rem", margin="2rem auto", padding="0 1rem")
	page.style("header", display="flex", gap="1rem", align_items="center", border_bottom="1px solid #ddd", padding_bottom="0.75rem")
	page.style(".UserMenu", margin_left="auto", display="flex", gap="0.75rem", align_items="center")
	page.style("form", display="flex", flex_direction="column", gap="0.5rem", max_width="20rem")
	page.style(".Notes form", flex_direction="row")
	page.style("label", display="flex", flex_direction="column", gap="0.25rem")
	page.style("input", font="inherit", padding="0.4rem")
	page.style(".error", color="#b00020")

	return page
