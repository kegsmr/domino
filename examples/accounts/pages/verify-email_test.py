# Tests for pages/verify-email.py. settings.json turns on accounts.verify_email, so signing up
# emails a link; in tests it lands in mail_outbox instead of being sent

from urllib.parse import urlsplit


def link(message):

	url = urlsplit(message.links[0])

	return f"{url.path}?{url.query}"


def test_sign_up_verify_the_link_and_log_in(page, mail_outbox):

	page.load("/signup?next=/members")
	page.fill("input[name=email]", "ada@example.com")
	page.fill("input[name=password]", "correct horse battery")
	page.click("button", text="Sign up")

	# Members need a verified email
	assert page.path == "/check-email"
	assert mail_outbox[0].to == ["ada@example.com"]
	page.click("button", text="Log out")

	page.load(link(mail_outbox[0]))
	assert page.text("main p") == "Your email is verified."
	page.load(page.find("main a", text="Continue").attrs["href"])
	assert page.path == "/login"

	page.fill("input[name=email]", "ada@example.com")
	page.fill("input[name=password]", "correct horse battery")
	page.click("button", text="Log in")

	assert page.path == "/members"
	assert page.text("main p") == "Your email, ada@example.com, is verified."


def test_a_bad_link_is_refused(page):

	page.load("/verify-email?token=forged")

	assert page.text("main p") == "This link is invalid or has expired."


def test_the_check_email_page_sends_the_link_again(page, mail_outbox):

	page.load("/signup")
	page.fill("input[name=email]", "ada@example.com")
	page.fill("input[name=password]", "correct horse battery")
	page.click("button", text="Sign up")

	page.load("/members")
	page.click("button", text="Send it again")

	assert "Sent. Check your inbox." in page.text("main")
	assert len(mail_outbox) == 2
