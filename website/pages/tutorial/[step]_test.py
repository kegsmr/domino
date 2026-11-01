# Tests for pages/tutorial/[step].py: each step renders, shows its app's real files, and its
# demos are that app's components, working on the page

import content


def inside(node, tag):
	"""The first element named `tag` inside `node`, or None."""

	return next((element for element in node.elements() if element.tag == tag), None)


def test_every_step_renders(open_page):

	for step in content.STEPS:
		page = open_page(step=step.slug)
		assert page.status == 200, step.slug
		assert page.text("h1") == step.title
		assert page.text(".eyebrow") == f"Tutorial · step {step.number} of {len(content.STEPS)}"
		assert page.find(".Sidebar a[aria-current=page]").text == f"{step.number}. {step.title}"
		# Every heading of the step is in its table of contents
		assert [link.text for link in page.find_all(".Toc a")] == content.step_headings(step)


def test_links_to_the_guide_go_to_its_pages(open_page):

	# The step's markdown links to ../guide/instant-ui.md, so it works on GitHub too
	page = open_page(step="2-events-and-forms")
	assert page.find("a", text="Instant UI").attrs["href"] == "/guide/instant-ui"

	page = open_page(step="8-deploying")
	assert page.find("a", text="guide").attrs["href"] == "/guide"
	assert page.find("a", text="Components").attrs["href"] == "/guide/components"


def test_steps_show_the_files_of_their_app(open_page):

	page = open_page(step="1-first-page")
	shown = {inside(code, "figcaption").text: inside(code, "pre").text for code in page.find_all(".Code") if inside(code, "figcaption")}

	for name in ("pages/index.py", "components/tasks.py"):
		source = (content.STEP_APPS / "1-first-page" / name).read_text(encoding="utf-8")
		assert shown[f"{name} Copy"] == " ".join(source.split())


def test_first_step_demo(open_page):

	page = open_page(step="1-first-page")

	assert page.text(".Demo .Tasks p") == "2 tasks"

	page.click(".Demo button", text="Add a task")

	assert page.text(".Demo .Tasks p") == "3 tasks"
	assert page.find_all(".Demo li")[-1].text == "Task 3"


def test_events_and_forms_demo(open_page):

	page = open_page(step="2-events-and-forms")

	page.fill(".Demo input[name=text]", "Water the plants")
	page.click(".Demo button", text="Add")

	assert page.find_all(".Demo li")[-1].text == "Water the plants"
	assert page.value(".Demo input[name=text]") == ""
	assert page.text(".Demo .Tasks p") == "2 left Clear done"

	page.click(".Demo button", text="Clear done")

	assert [item.text for item in page.find_all(".Demo li")] == ["Build something", "Water the plants"]


def test_styles_demo_brings_its_css(open_page):

	page = open_page(step="3-styles")

	# The step component's own css, scoped to it, in the docs page's <head>
	assert ".Tasks li.done {" in page.html
	assert page.find(".Demo li").attrs["class"] == "done"


def test_shared_demo_updates_every_open_page(open_page):

	ada = open_page(step="5-reactive-data")
	grace = open_page(step="5-reactive-data")

	# Started with two tasks, for everyone
	assert len(ada.find_all(".Demo li")) >= 2

	ada.fill(".Demo input[name=text]", "Say hi to Grace")
	ada.click(".Demo button", text="Add")
	grace.sync()

	assert grace.find_all(".Demo li")[-1].text == "Say hi to Grace"


def test_steps_without_a_demo_show_only_code(open_page):

	page = open_page(step="6-accounts")

	assert page.find_all(".Demo") == []
	assert inside(page.find(".Code", text="accounts.UserMenu()"), "figcaption").text == "pages/layout.py Copy"


def test_unknown_steps_are_not_found(open_page):

	assert open_page(step="9-nothing").status == 404
