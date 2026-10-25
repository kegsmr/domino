# Tests for pages/reset-password.py: the whole "forgot your password?" flow. Emails aren't
# sent in tests; mail_outbox has them


import time
from urllib.parse import urlsplit

from domino import accounts


def sign_up(page, email="ada@example.com", password="correct horse battery"):

	page.load("/signup")
	page.fill("input[name=email]", email)
	page.fill("input[name=password]", password)
	page.click("button", text="Sign up")
	page.click("button", text="Log out")


def ask_for_a_link(page, email="ada@example.com"):

	page.load("/login")
	page.load(page.find("a", text="Forgot your password?").attrs["href"])
	page.fill("input[name=email]", email)
	page.click("button", text="Email me a link")


def link(message):

	url = urlsplit(message.links[0])

	return f"{url.path}?{url.query}"


def log_in(page, password, email="ada@example.com"):

	page.load("/login")
	page.fill("input[name=email]", email)
	page.fill("input[name=password]", password)
	page.click("button", text="Log in")


def test_without_a_link_it_says_so(page):

	assert page.text("main p") == "This link is invalid or has expired."


def test_forgot_password_email_reset_and_log_in(page, mail_outbox):

	sign_up(page)
	mail_outbox.clear()  # the verification email

	ask_for_a_link(page)
	assert page.text("main p").startswith("If an account exists for that email")
	assert mail_outbox[0].subject == "Reset your password"

	page.load(link(mail_outbox[0]))
	page.fill("input[name=password]", "a new password")
	page.fill("input[name=confirm]", "a new password")
	page.click("button", text="Change password")
	assert page.text("main p") == "Your password has been changed."

	assert page.find("main a").attrs["href"] == "/login"

	log_in(page, "correct horse battery")
	assert page.text("[role=alert]") == "Wrong email or password"

	log_in(page, "a new password")
	assert "Signed in as ada@example.com" in page.text("header")


def test_a_used_link_is_rejected(page, mail_outbox):

	sign_up(page)
	ask_for_a_link(page)
	path = link(mail_outbox[-1])

	page.load(path)
	page.fill("input[name=password]", "a new password")
	page.fill("input[name=confirm]", "a new password")
	page.click("button", text="Change password")

	page.load(path)
	assert page.text("main p") == "This link is invalid or has expired."


def test_an_expired_link_is_rejected(page, mail_outbox, monkeypatch):

	sign_up(page)
	ask_for_a_link(page)

	# An hour and a bit later
	later = time.time() + 3601
	monkeypatch.setattr(accounts, "_clock", lambda: later)

	page.load(link(mail_outbox[-1]))
	assert page.text("main p") == "This link is invalid or has expired."
