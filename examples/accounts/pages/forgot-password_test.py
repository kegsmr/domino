# Tests for pages/forgot-password.py

from domino import accounts


def test_reset_email(page, mail_outbox):

	accounts.create_user("ada@example.com", "correct horse")
	page.fill("input[name=email]", "ada@example.com")
	page.click("button", text="Email me a link")

	assert mail_outbox[0].subject == "Reset your password"


def test_the_same_answer_without_an_account(page, mail_outbox):

	page.fill("input[name=email]", "nobody@example.com")
	page.click("button", text="Email me a link")

	assert page.text("main p") == "If an account exists for that email, we've emailed a link to reset your password."
	assert mail_outbox == []
