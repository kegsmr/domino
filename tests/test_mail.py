import base64
import email
import email.policy
import logging
import socketserver
import threading

import pytest

from domino import Domino, mail


class FakeSMTP(socketserver.ThreadingTCPServer):
	"""Just enough of an SMTP server, on a free port, to receive emails from smtplib."""

	daemon_threads = True
	allow_reuse_address = True


	def __init__(self, password=None):

		super().__init__(("127.0.0.1", 0), SMTPHandler)
		self.port = self.server_address[1]
		self.password = password
		self.received = []  # (logins, sender, recipients, message)
		self.done = threading.Event()
		threading.Thread(target=self.serve_forever, daemon=True).start()


class SMTPHandler(socketserver.StreamRequestHandler):


	def reply(self, line):

		self.wfile.write(line.encode() + b"\r\n")


	def handle(self):

		server = self.server
		logins = []
		sender, recipients = None, []
		self.reply("220 fake ESMTP")

		while True:
			line = self.rfile.readline().decode().rstrip("\r\n")
			if not line:
				return
			command = line.split(" ", 1)[0].upper()

			if command == "EHLO":
				self.reply("250-fake")
				self.reply("250 AUTH PLAIN")
			elif command == "AUTH":
				_, user, password = base64.b64decode(line.split()[2]).split(b"\0")
				if password.decode() != server.password:
					self.reply("535 bad credentials")
					continue
				logins.append(user.decode())
				self.reply("235 ok")
			elif command == "MAIL":
				sender = line.split(":", 1)[1].strip().strip("<>")
				self.reply("250 ok")
			elif command == "RCPT":
				recipients.append(line.split(":", 1)[1].strip().strip("<>"))
				self.reply("250 ok")
			elif command == "DATA":
				self.reply("354 go on")
				data = b""
				while True:
					chunk = self.rfile.readline()
					if chunk in (b".\r\n", b""):
						break
					data += chunk
				message = email.message_from_bytes(data, policy=email.policy.default)
				server.received.append((logins, sender, recipients, message))
				server.done.set()
				self.reply("250 queued")
			elif command == "QUIT":
				self.reply("221 bye")
				return
			else:
				self.reply("250 ok")


@pytest.fixture
def smtp():

	servers = []

	def start(**options):
		server = FakeSMTP(**options)
		servers.append(server)
		return server

	yield start

	for server in servers:
		server.shutdown()
		server.server_close()


@pytest.fixture
def not_testing(monkeypatch):
	"""As if outside pytest, so the settings choose the backend."""

	monkeypatch.setattr(mail, "testing", False)


def make_app(debug=False, **settings):

	app = Domino(__name__)
	app.debug = debug
	if settings:
		app.settings["mail"] = settings

	return app


def test_tests_keep_emails_in_the_outbox(mail_outbox):

	# Whatever the settings say: tests never send real email
	app = make_app(backend="smtp", host="mail.invalid", **{"from": "app@example.com"})

	with app.app_context():
		message = mail.send("ada@example.com", "Hello", "Visit http://localhost/x?token=abc.\n", html="<p>Hi</p>")

	assert mail_outbox == [message]
	assert message.to == ["ada@example.com"]
	assert message.subject == "Hello"
	assert message.html == "<p>Hi</p>"
	assert message.sender == "app@example.com"
	assert message.links == ["http://localhost/x?token=abc."]


def test_outbox_starts_empty_in_each_test(mail_outbox):

	assert mail_outbox == []


def test_backend_comes_from_settings_and_debug(not_testing):

	assert mail.backend_name({"backend": "smtp"}, debug=True) == "smtp"
	assert mail.backend_name({"backend": "memory"}, debug=False) == "memory"
	assert mail.backend_name({}, debug=True) == "console"

	with pytest.raises(mail.MailConfigError, match="no mail backend is set up.*DOMINO_MAIL__PASSWORD"):
		mail.backend_name({}, debug=False)
	with pytest.raises(mail.MailConfigError, match="Unknown mail backend 'sendmail'"):
		mail.backend_name({"backend": "sendmail"}, debug=True)


def test_sending_outside_debug_without_a_backend_raises(not_testing):

	with make_app().app_context():
		with pytest.raises(mail.MailConfigError):
			mail.send("ada@example.com", "Hello", "Hi")


def test_console_backend_prints_the_email(not_testing, capsys):

	with make_app(debug=True).app_context():
		mail.send(["ada@example.com", "bob@example.com"], "Reset", "Open this:\n\nhttp://localhost/reset?token=abc\n")

	printed = capsys.readouterr().err
	assert "To: ada@example.com, bob@example.com" in printed
	assert "Subject: Reset" in printed
	# On a line of its own, so terminals make it clickable
	assert "\nhttp://localhost/reset?token=abc\n" in printed


def test_memory_backend_from_settings(not_testing):

	mail.outbox.clear()
	with make_app(backend="memory").app_context():
		mail.send("ada@example.com", "Hello", "Hi")

	assert [message.subject for message in mail.outbox] == ["Hello"]
	mail.outbox.clear()


def test_smtp_backend_sends_in_the_background(not_testing, smtp):

	server = smtp(password="s3cret")
	app = make_app(backend="smtp", host="127.0.0.1", port=server.port, username="app", password="s3cret", **{"from": "My App <app@example.com>"})

	with app.app_context():
		mail.send("ada@example.com", "Hello", "Plain text", html="<p>HTML</p>")

	assert mail.flush(10)
	assert server.done.wait(5)
	logins, sender, recipients, message = server.received[0]
	assert logins == ["app"]
	assert sender == "app@example.com" and recipients == ["ada@example.com"]
	assert message["Subject"] == "Hello" and message["From"] == "My App <app@example.com>"
	assert message.get_body(("plain",)).get_content().strip() == "Plain text"
	assert message.get_body(("html",)).get_content().strip() == "<p>HTML</p>"


def test_smtp_password_from_the_environment(not_testing, smtp, monkeypatch):

	server = smtp(password="from env")
	monkeypatch.setenv("DOMINO_MAIL__PASSWORD", "from env")
	monkeypatch.setenv("DOMINO_MAIL__BACKEND", "smtp")
	monkeypatch.setenv("DOMINO_MAIL__PORT", str(server.port))
	app = make_app()
	app.settings["mail"].update({"host": "127.0.0.1", "username": "app@example.com"})

	with app.app_context():
		message = mail.send("ada@example.com", "Hello", "Hi")

	# The username is the sender when it's an address and there's no mail.from
	assert message.sender == "app@example.com"
	assert mail.flush(10) and server.done.wait(5)
	assert server.received[0][0] == ["app@example.com"]


def test_smtp_failures_are_logged_not_raised(not_testing, smtp, caplog):

	server = smtp(password="right")
	app = make_app(backend="smtp", host="127.0.0.1", port=server.port, username="app", password="wrong", **{"from": "app@example.com"})

	with caplog.at_level(logging.ERROR, logger="domino.mail"):
		with app.app_context():
			mail.send("ada@example.com", "Hello", "Hi")
		assert mail.flush(10)

	assert "Couldn't send the email 'Hello' to ada@example.com" in caplog.text
	assert server.received == []


def test_smtp_tls_and_timeout_settings(not_testing, monkeypatch):

	calls = []

	class Connection:

		def __init__(self, host, port, timeout):
			calls.append(("connect", host, port, timeout))

		def __enter__(self):
			return self

		def __exit__(self, *exc):
			calls.append(("quit",))

		def starttls(self, context):
			calls.append(("starttls",))

		def login(self, username, password):
			calls.append(("login", username, password))

		def send_message(self, message):
			calls.append(("send", message["To"]))

	monkeypatch.setattr(mail.smtplib, "SMTP", Connection)
	message = mail.Message("ada@example.com", "Hi", "Hi", sender="app@example.com")
	mail.deliver(message, {"host": "smtp.example.com", "tls": True, "username": "app", "password": "pw", "timeout": 3})

	assert calls == [("connect", "smtp.example.com", 587, 3.0), ("starttls",), ("login", "app", "pw"), ("send", "ada@example.com"), ("quit",)]


def test_smtp_needs_a_from_address(not_testing):

	with make_app(backend="smtp", host="127.0.0.1").app_context():
		with pytest.raises(mail.MailConfigError, match="mail.from"):
			mail.send("ada@example.com", "Hello", "Hi")


def test_header_injection_and_empty_recipients_are_refused(mail_outbox):

	with make_app().app_context():
		with pytest.raises(ValueError):
			mail.send("ada@example.com", "Hello\r\nBcc: eve@example.com", "Hi")
		with pytest.raises(ValueError):
			mail.send([], "Hello", "Hi")

	assert mail_outbox == []
