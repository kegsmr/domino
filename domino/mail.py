"""Sending email: mail.send(to, subject, text, html=None).

	from domino import mail

	mail.send("ada@example.com", "Welcome", "Thanks for signing up.")

The backend comes from the "mail" settings:

	{"mail": {"backend": "smtp", "host": "smtp.example.com", "port": 587, "tls": true,
	          "username": "...", "password": "...", "from": "My App <noreply@example.com>"}}

"console" prints each email to the server's output instead of sending it, and "memory" keeps
them in mail.outbox. With no backend set, debug mode uses "console" and tests use "memory"
(always, so tests never send real email); anywhere else sending raises MailConfigError.

SMTP emails are sent by one background thread, so send() returns at once: an event handler
doesn't wait seconds for a mail server, and a reply doesn't take longer when an email is sent
(which would tell a visitor whether a password reset found an account). A failed delivery is
logged. Emails still queued when the process exits get a few seconds to go out.
"""

import atexit
import logging
import os
import queue
import re
import smtplib
import ssl
import sys
import threading
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from flask import current_app, has_app_context

from . import mongo


log = logging.getLogger(__name__)

BACKENDS = ("smtp", "console", "memory")

# Sent emails, when the backend is "memory" (in tests: the mail_outbox fixture)
outbox = []

# None: use the memory backend while pytest runs a test. Tests of the settings set it to False
testing = None


class MailError(RuntimeError):
	"""An email couldn't be sent."""


class MailConfigError(MailError):
	"""The app isn't set up to send email."""


class Message:
	"""An email: who it's to, its subject, its text and (optionally) its HTML."""


	def __init__(self, to, subject, text, html=None, sender=None):

		if isinstance(to, str):
			to = [to]
		self.to = [str(address).strip() for address in to]
		self.subject = str(subject)
		self.text = str(text)
		self.html = None if html is None else str(html)
		self.sender = sender

		if not self.to or not all(self.to):
			raise ValueError("An email needs at least one address to send it to")


	@property
	def links(self):
		"""The URLs in the text, in order."""

		return re.findall(r"https?://[^\s<>\"']+", self.text)


	def email(self):
		"""The email.message.EmailMessage to send. Raises ValueError for a header with a line break."""

		message = EmailMessage()
		message["From"] = self.sender
		message["To"] = ", ".join(self.to)
		message["Subject"] = self.subject
		message["Date"] = formatdate(localtime=True)
		message["Message-ID"] = make_msgid()
		message.set_content(self.text)
		if self.html is not None:
			message.add_alternative(self.html, subtype="html")

		return message


	def __repr__(self):

		return f"<Message to={self.to!r} subject={self.subject!r}>"


def _app():

	if has_app_context():
		return current_app._get_current_object()

	# Pushes and background threads run outside any request; use the app Domino() registered
	if mongo._app is not None:
		return mongo._app()

	return None


def _testing():

	if testing is not None:
		return testing

	# Set by pytest while it runs a test, also seen by the app's threads (a browser test's server)
	return "PYTEST_CURRENT_TEST" in os.environ


def settings():
	"""The app's "mail" settings."""

	app = _app()
	if app is None:
		return {}

	return app.settings.get("mail") or {}


def backend_name(config=None, debug=None):
	"""The backend send() uses: memory in tests, else the mail.backend setting, else console in debug mode."""

	if _testing():
		return "memory"

	if config is None:
		config = settings()
	if debug is None:
		app = _app()
		debug = bool(app is not None and app.debug)

	name = config.get("backend")
	if name:
		if name not in BACKENDS:
			raise MailConfigError(f"Unknown mail backend {name!r} (the mail.backend setting): use one of {', '.join(BACKENDS)}")
		return name

	if debug:
		return "console"

	raise MailConfigError(
		"Can't send email: no mail backend is set up. Add SMTP settings, e.g. in settings.json "
		"{\"mail\": {\"backend\": \"smtp\", \"host\": \"smtp.example.com\", \"port\": 587, \"tls\": true, "
		"\"username\": \"...\", \"from\": \"noreply@example.com\"}} with the password in "
		"DOMINO_MAIL__PASSWORD, or set mail.backend to \"console\" to print emails instead."
	)


def send(to, subject, text, html=None):
	"""Send an email to `to` (an address or a list of them) with a plain-text body and,
	optionally, an HTML one. Returns the Message. SMTP emails are sent in the background."""

	config = settings()
	name = backend_name(config)

	sender = config.get("from")
	if not sender and name == "smtp" and "@" in str(config.get("username") or ""):
		sender = config["username"]
	if not sender:
		if name == "smtp":
			raise MailConfigError("Set mail.from to the address emails are sent from, e.g. \"My App <noreply@example.com>\"")
		sender = "webmaster@localhost"

	message = Message(to, subject, text, html, sender)
	# Built now, so a bad address or header fails here rather than in the background
	message.email()

	if name == "memory":
		outbox.append(message)
	elif name == "console":
		_print(message)
	else:
		_queue.put((message, dict(config)))
		_start_worker()

	return message


def _print(message):

	rule = "-" * 72
	lines = [
		"",
		rule,
		"Email (mail backend \"console\", not sent)",
		f"From: {message.sender}",
		f"To: {', '.join(message.to)}",
		f"Subject: {message.subject}",
		"",
		message.text.rstrip(),
	]
	if message.html is not None:
		lines += ["", "(and an HTML version)"]
	lines += [rule, ""]

	# Links are on lines of their own, so terminals make them clickable
	print("\n".join(lines), file=sys.stderr, flush=True)


def deliver(message, config):
	"""Send `message` over SMTP now, with the "mail" settings `config`."""

	host = config.get("host") or "localhost"
	use_ssl = bool(config.get("ssl"))
	use_tls = bool(config.get("tls")) and not use_ssl
	port = int(config.get("port") or (465 if use_ssl else 587 if use_tls else 25))
	timeout = float(config.get("timeout") or 10)

	if use_ssl:
		connection = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
	else:
		connection = smtplib.SMTP(host, port, timeout=timeout)

	with connection:
		if use_tls:
			connection.starttls(context=ssl.create_default_context())
		if config.get("username"):
			connection.login(str(config["username"]), str(config.get("password") or ""))
		connection.send_message(message.email())


_queue = queue.Queue()
_worker = [None]
_worker_lock = threading.Lock()


def _start_worker():

	with _worker_lock:
		if _worker[0] is not None and _worker[0].is_alive():
			return
		_worker[0] = threading.Thread(target=_work, name="domino-mail", daemon=True)
		_worker[0].start()


def _work():

	while True:
		message, config = _queue.get()
		try:
			deliver(message, config)
		except Exception as error:
			log.error("Couldn't send the email %r to %s: %s", message.subject, ", ".join(message.to), error)
		finally:
			_queue.task_done()


def flush(timeout=10):
	"""Wait up to `timeout` seconds for queued SMTP emails to be sent. True if none are left."""

	deadline = time.monotonic() + timeout
	with _queue.all_tasks_done:
		while _queue.unfinished_tasks:
			remaining = deadline - time.monotonic()
			if remaining <= 0:
				return False
			_queue.all_tasks_done.wait(remaining)

	return True


@atexit.register
def _flush_at_exit():

	if _worker[0] is not None and not flush(5):
		log.error("Emails still queued at exit weren't sent")
