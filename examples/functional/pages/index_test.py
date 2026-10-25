def test_home_links_to_people_and_marks_itself_in_the_nav(page):

	assert page.text("h1") == "Welcome to My Website"
	assert page.find("nav a[aria-current=page]").text == "Home"
	assert [link.attrs["href"] for link in page.find_all("main li a")] == ["/hello/Ada", "/hello/Grace", "/hello/Linus"]


def test_other_pages_and_the_404_page(open_page):

	about = open_page("/about")
	missing = open_page("/nowhere")

	assert about.find("nav a[aria-current=page]").text == "About"
	assert missing.status == 404
	assert missing.text("h1") == "Page not found"
