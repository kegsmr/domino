# Email

Sending email, printed while debugging and captured in tests.

`domino.mail.send(to, subject, text, html=None)` sends an email (`to` is an address or a list of them). Set up SMTP in the settings, with the password in `settings.local.json` or the environment (`DOMINO_MAIL__PASSWORD`):

```json
{"mail": {"backend": "smtp", "host": "smtp.example.com", "port": 587, "tls": true, "username": "apikey", "from": "My App <noreply@example.com>"}}
```

- `"tls": true` uses STARTTLS (port 587 by default), `"ssl": true` a TLS connection from the start (port 465); `timeout` is in seconds (default 10).
- SMTP emails are sent by a background thread, so `send()` returns at once: event handlers don't wait seconds for a mail server, and a page doesn't answer slower when an email goes out. A failed delivery is logged, not raised, and emails still queued when the process exits get a few seconds to go out.
- The `"console"` backend prints each email to the server's output instead (links on lines of their own, so terminals make them clickable); it's the default in debug mode. The `"memory"` backend keeps them in `domino.mail.outbox`.
- In tests the memory backend is always used, whatever the settings, so tests never send real email. The `mail_outbox` fixture gives the emails sent during the test (each has `.to`, `.subject`, `.text`, `.html` and `.links`):

```python
# pages/forgot-password_test.py
from domino import accounts

def test_reset_email(page, mail_outbox):
    accounts.create_user("ada@example.com", "correct horse")
    page.fill("input[name=email]", "ada@example.com")
    page.click("button", text="Email me a link")
    assert mail_outbox[0].subject == "Reset your password"
```

- Outside debug mode and tests, sending without a backend raises `domino.mail.MailConfigError`.
