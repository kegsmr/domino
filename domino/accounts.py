"""User accounts, like Meteor's accounts packages: sign-up, login, logout and the current user.

Users are documents in the named Collection "users" (MongoDB). The signed-in user's id is kept
in Flask's signed session cookie and bound to each Domino page when the page is made, so event
handlers and server pushes (which run outside the user's request) know who is on the page.
current_user() is reactive: components that show it re-render when the user logs in or out.

	from domino import accounts

	@app.route("/private")
	@accounts.login_required
	def private():
		return Document() [accounts.UserMenu(), t.p() [accounts.current_user()["email"]]]
"""

import functools
import hmac
import json
import logging
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import flask
from flask import current_app, has_app_context, has_request_context, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from . import mongo
from . import tags as t
from .core import DEFAULT_PAGE, SESSION_USER_KEY, Page, redirect
from .reactive import Collection, State
from .util import is_local_url


log = logging.getLogger(__name__)

# Server-side only: render fields from it, never whole documents (they hold password hashes)
users = Collection("users")

MIN_PASSWORD_LENGTH = 8

# Hashing a huge "password" is slow, so longer ones are refused before hashing
MAX_PASSWORD_LENGTH = 1024

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

WRONG_LOGIN = "Wrong email or password"

STATE_KEY = "domino_oauth_state"
NEXT_KEY = "domino_oauth_next"
ERROR_KEY = "domino_accounts_error"


class AccountError(ValueError):
	"""Something the user can fix; str(error) is a message to show them."""


class AccountsConfigError(RuntimeError):
	"""The app isn't set up for accounts (e.g. no secret_key)."""


class OAuthError(RuntimeError):
	"""A provider's token or user-info request failed."""


def _app():

	if has_app_context():
		return current_app._get_current_object()

	# Pushes run outside any request; use the app Domino() registered with domino.mongo
	if mongo._app is not None:
		return mongo._app()

	return None


def settings():
	"""The app's "accounts" settings (login_url, github, google, ...)."""

	app = _app()
	if app is None:
		return {}

	return app.settings.get("accounts") or {}


def login_url():

	return settings().get("login_url") or "/login"


def signup_url():

	return settings().get("signup_url") or "/signup"


_key_lock = threading.Lock()


def _ensure_secret_key():
	"""Session cookies are signed with the app's secret_key. While debugging, make one up."""

	app = current_app._get_current_object()
	if app.secret_key:
		return

	with _key_lock:
		if app.secret_key:
			return
		if not app.debug:
			raise AccountsConfigError(
				"Accounts need a secret key to sign session cookies. Set secret_key in "
				"settings.local.json (or the DOMINO_SECRET_KEY environment variable) to a long "
				"random string, e.g. the output of: python -c \"import secrets; print(secrets.token_hex(32))\""
			)
		app.secret_key = secrets.token_hex(32)
		log.warning(
			"No secret_key setting: using a random one for this process, so logins won't survive "
			"a restart. Set secret_key in settings.local.json or DOMINO_SECRET_KEY to keep them."
		)


def _session_is_open():

	# The session is opened before the request is handled, so it can't be written in the
	# request during which _ensure_secret_key() made up a key
	_ensure_secret_key()

	return not current_app.session_interface.is_null_session(session._get_current_object())


_indexed = set()
_indexed_lock = threading.Lock()


def _users():
	"""The users collection, with its unique indexes when it's in MongoDB."""

	store = users.store()
	if not isinstance(store, mongo.MongoStore):
		return users

	collection = store.collection
	key = (id(collection.database.client), collection.full_name)
	if key in _indexed:
		return users

	with _indexed_lock:
		if key not in _indexed:
			# Sparse: users who signed in with a provider that gave no verified email have none
			collection.create_index("email", unique=True, sparse=True)
			collection.create_index("services.github.id", unique=True, sparse=True)
			collection.create_index("services.google.id", unique=True, sparse=True)
			_indexed.add(key)

	return users


def _public(user):
	"""A user document without its password hash, safe to hand to app code."""

	if user is None:
		return None

	user.pop("password_hash", None)

	return user


def _insert_user(document):

	try:
		return _users().insert(document)
	except Exception as error:
		# Two sign-ups with the same email at once: the unique index catches the second
		if type(error).__name__ == "DuplicateKeyError":
			raise AccountError("An account with this email already exists") from None
		raise


def normalize_email(email):

	return str(email or "").strip().lower()


def create_user(email, password, name=None):
	"""Create a user with a password and return it (without the password hash).
	Raises AccountError with a message for the user when the input won't do."""

	email = normalize_email(email)
	if not EMAIL_PATTERN.match(email) or len(email) > 254:
		raise AccountError("Enter a valid email address")
	if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
		raise AccountError(f"Use a password of at least {MIN_PASSWORD_LENGTH} characters")
	if len(password) > MAX_PASSWORD_LENGTH:
		raise AccountError(f"Use a password of at most {MAX_PASSWORD_LENGTH} characters")
	if _users().find_one({"email": email}):
		raise AccountError("An account with this email already exists")

	name = str(name or "").strip() or None
	user_id = _insert_user({
		"email": email,
		"password_hash": generate_password_hash(password),
		"name": name,
		"created": datetime.now(timezone.utc),
		"services": {},
	})

	return _public(_users().find_one({"_id": user_id}))


# Checked when there's no such user, so a wrong email takes as long as a wrong password
_dummy_hash = None


def _check_password(user, password):

	global _dummy_hash

	stored = None
	if user is not None:
		stored = user.get("password_hash")
	if not stored:
		if _dummy_hash is None:
			_dummy_hash = generate_password_hash(secrets.token_hex(16))
		check_password_hash(_dummy_hash, password)
		return False

	return check_password_hash(stored, password)


# Failed logins per email and per IP address, kept in this process only
_failures = {}
_failures_lock = threading.Lock()


def _recent_failures(key, window, now):
	"""Failures for `key` in the last `window` seconds. Call with _failures_lock held."""

	times = [moment for moment in _failures.get(key, ()) if moment > now - window]
	if times:
		_failures[key] = times
	else:
		_failures.pop(key, None)

	return times


def _limits(email):

	config = settings()
	attempts = int(config.get("max_attempts") or 5)
	window = float(config.get("lockout_seconds") or 60)

	# Several people can share an address (offices, phone networks), so it gets more tries
	limits = [(f"email:{email}", attempts)]
	if has_request_context() and request.remote_addr:
		limits.append((f"ip:{request.remote_addr}", attempts * 4))

	return limits, window


def _locked(limits, window):

	now = time.monotonic()
	with _failures_lock:
		return any(len(_recent_failures(key, window, now)) >= limit for key, limit in limits)


def _record_failure(limits, window):

	now = time.monotonic()
	with _failures_lock:
		# Forget old entries now and then, so the table can't grow without bound
		if len(_failures) > 10000:
			for key in list(_failures):
				_recent_failures(key, window, now)
		for key, _ in limits:
			_failures.setdefault(key, []).append(now)


def _sign_in(user_id):

	if not _session_is_open():
		raise AccountError("Your session expired. Reload the page and try again.")

	# A fresh session, so nothing planted in the old cookie carries over (session fixation)
	session.clear()
	session[SESSION_USER_KEY] = user_id
	session.permanent = True

	page = Page.current()
	if page is not DEFAULT_PAGE:
		page.user_id.value = user_id


def login(email, password):
	"""Sign in on this page and in the browser's session cookie, and return the user.
	Raises AccountError("Wrong email or password") whatever was wrong, or when locked out."""

	_ensure_secret_key()

	email = normalize_email(email)
	limits, window = _limits(email)
	if _locked(limits, window):
		raise AccountError("Too many failed attempts. Try again in a minute.")

	user = None
	if isinstance(password, str) and len(password) <= MAX_PASSWORD_LENGTH and email:
		user = _users().find_one({"email": email})
	if not _check_password(user, str(password or "")[:MAX_PASSWORD_LENGTH]):
		_record_failure(limits, window)
		raise AccountError(WRONG_LOGIN)

	with _failures_lock:
		_failures.pop(f"email:{email}", None)

	_sign_in(user["_id"])

	return _public(user)


def logout():
	"""Sign out on this page and clear the browser's session cookie."""

	if _session_is_open():
		session.clear()

	page = Page.current()
	if page is not DEFAULT_PAGE:
		page.user_id.value = None


def user_id():
	"""The signed-in user's id on this page, or None. Reactive, like current_user()."""

	if has_request_context():
		_ensure_secret_key()

	return Page.current().user_id.value


def current_user():
	"""The signed-in user's document (without the password hash), or None.

	Reading it in render() subscribes the component, so it re-renders when this page's
	user logs in or out. Changes to the user document itself don't re-render it."""

	uid = user_id()
	if uid is None:
		return None

	# Straight from the store: subscribing to the whole users collection would re-render
	# every page's user menu whenever anyone signs up
	found = _users().store().find({"_id": uid}, None, 1)
	if not found:
		return None

	return _public(dict(found[0]))


def login_required(function):
	"""For route functions and page() functions: visitors who aren't signed in are sent to the login page
	(the accounts.login_url setting, default /login) with ?next= pointing back here."""

	@functools.wraps(function)
	def wrapper(*args, **kwargs):

		if current_user() is None:
			here = request.full_path.rstrip("?")
			separator = "?"
			if "?" in login_url():
				separator = "&"
			return flask.redirect(login_url() + separator + urllib.parse.urlencode({"next": here}))

		return function(*args, **kwargs)

	return wrapper


def safe_next(url):
	"""`url` if it's a path on this site, else None (so ?next= can't send users elsewhere)."""

	if is_local_url(url):
		return url

	return None


def _next_from_request():

	if has_request_context():
		return safe_next(request.args.get("next"))

	return None


# OAuth providers, used when the app has accounts.<provider>.client_id and client_secret

PROVIDERS = {
	"github": {
		"title": "GitHub",
		"authorize_url": "https://github.com/login/oauth/authorize",
		"token_url": "https://github.com/login/oauth/access_token",
		"scope": "read:user user:email",
	},
	"google": {
		"title": "Google",
		"authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
		"token_url": "https://oauth2.googleapis.com/token",
		"scope": "openid email profile",
	},
}


def provider_config(provider):
	"""The provider's client_id and client_secret from settings, or None if it isn't set up."""

	if provider not in PROVIDERS:
		return None

	config = settings().get(provider) or {}
	if not config.get("client_id") or not config.get("client_secret"):
		return None

	return config


def _fetch_json(url, data=None, token=None):
	"""GET (or POST `data`, form-encoded) and parse the JSON response."""

	headers = {"Accept": "application/json", "User-Agent": "domino-accounts"}
	if token:
		headers["Authorization"] = f"Bearer {token}"

	body = None
	if data is not None:
		body = urllib.parse.urlencode(data).encode("utf-8")

	try:
		with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=10) as response:
			return json.loads(response.read().decode("utf-8"))
	except (urllib.error.URLError, ValueError) as error:
		raise OAuthError(f"{url}: {error}") from None


def _github_profile(token):

	user = _fetch_json("https://api.github.com/user", token=token)
	emails = _fetch_json("https://api.github.com/user/emails", token=token)

	if not isinstance(emails, list):
		emails = []

	primary = {}
	for entry in emails:
		if entry.get("primary"):
			primary = entry

	return {
		"id": str(user["id"]),
		"email": primary.get("email"),
		"verified": primary.get("verified") is True,
		"name": user.get("name") or user.get("login"),
		"username": user.get("login"),
	}


def _google_profile(token):

	user = _fetch_json("https://openidconnect.googleapis.com/v1/userinfo", token=token)

	return {
		"id": str(user["sub"]),
		"email": user.get("email"),
		"verified": user.get("email_verified") is True,
		"name": user.get("name"),
	}


PROFILES = {"github": _github_profile, "google": _google_profile}


def _oauth_user(provider, profile):
	"""The user for this provider account: already linked, else the user with the same
	verified email (now linked), else a new user."""

	service = {key: value for key, value in profile.items() if key != "verified"}
	field = f"services.{provider}"

	user = _users().find_one({f"{field}.id": service["id"]})
	if user is not None:
		_users().update({"_id": user["_id"]}, {"$set": {field: service}})
		return user

	email = normalize_email(profile.get("email"))
	existing = None
	if email:
		existing = _users().find_one({"email": email})

	# Only a verified email proves it's the same person; otherwise anyone could take over
	# an account by adding its address to their provider account
	if existing is not None and not profile.get("verified"):
		raise AccountError("An account with this email already exists. Log in with your password.")
	if existing is not None:
		_users().update({"_id": existing["_id"]}, {"$set": {field: service}})
		return existing

	document = {
		"password_hash": None,
		"name": profile.get("name"),
		"created": datetime.now(timezone.utc),
		"services": {provider: service},
	}
	if email and profile.get("verified"):
		document["email"] = email

	return _users().find_one({"_id": _insert_user(document)})


def _back_to_login(message):

	session[ERROR_KEY] = message

	return flask.redirect(login_url())


def oauth_view(provider, action):
	"""/_domino/accounts/<provider>/login and /callback (the authorization-code flow)."""

	config = provider_config(provider)
	if config is None or action not in ("login", "callback"):
		flask.abort(404)

	if not _session_is_open():
		# The secret key was only just made up (debug); the next request has a session
		return flask.redirect(request.full_path)

	callback = flask.url_for("domino_oauth", provider=provider, action="callback", _external=True)

	if action == "login":
		state = secrets.token_urlsafe(32)
		session[STATE_KEY] = state
		session[NEXT_KEY] = _next_from_request()
		query = urllib.parse.urlencode({
			"client_id": config["client_id"],
			"redirect_uri": callback,
			"response_type": "code",
			"scope": PROVIDERS[provider]["scope"],
			"state": state,
		})
		return flask.redirect(f"{PROVIDERS[provider]['authorize_url']}?{query}")

	# The state proves this callback answers a login this browser started (CSRF)
	expected = session.pop(STATE_KEY, None)
	next_url = safe_next(session.pop(NEXT_KEY, None))
	state = request.args.get("state", "")
	if not expected or not hmac.compare_digest(expected.encode("utf-8"), state.encode("utf-8")):
		return flask.Response("Invalid OAuth state. Go back and try signing in again.", 400, mimetype="text/plain")

	title = PROVIDERS[provider]["title"]
	code = request.args.get("code")
	if request.args.get("error") or not code:
		return _back_to_login(f"{title} sign-in was cancelled.")

	try:
		token = _fetch_json(PROVIDERS[provider]["token_url"], data={
			"client_id": config["client_id"],
			"client_secret": config["client_secret"],
			"code": code,
			"redirect_uri": callback,
			"grant_type": "authorization_code",
		}).get("access_token")
		if not token:
			raise OAuthError("no access_token in the token response")
		profile = PROFILES[provider](token)
	except (OAuthError, KeyError, TypeError, AttributeError) as error:
		log.warning("%s sign-in failed: %s", title, error)
		return _back_to_login(f"Couldn't sign in with {title}. Try again.")

	try:
		user = _oauth_user(provider, profile)
	except AccountError as error:
		return _back_to_login(str(error))

	_sign_in(user["_id"])

	return flask.redirect(next_url or "/")


# Ready-made components. Plain HTML; each has its class name (LoginForm, ...) for styling


def _field(event, name):

	value = event.form.get(name, "")
	if isinstance(value, list):
		value = value[-1]

	return str(value)


def _display_name(user):

	return user.get("name") or user.get("email") or "user"


class OAuthButton(t.a):
	"""A "Continue with GitHub" link, rendered only when the provider is set up in settings."""


	def __init__(self, provider, label=None, **kwargs):

		super().__init__(**kwargs)

		self.provider = provider
		self.label = label
		self.next_url = _next_from_request()


	def render(self):

		href = f"/_domino/accounts/{self.provider}/login"
		if self.next_url:
			href += "?" + urllib.parse.urlencode({"next": self.next_url})
		self.configure(href=href)

		return [self.label or f"Continue with {PROVIDERS[self.provider]['title']}"]


	def _render(self, level=0, indent=4):

		if provider_config(self.provider) is None:
			return ""

		return super()._render(level, indent)


class LoginForm(t.div):
	"""Email and password, with the error shown inline. Redirects to ?next= after logging in."""

	error = State(None)
	email = State("")  # kept in the form after a failed attempt


	def init(self):

		self.next_url = _next_from_request()

		# Set by a failed OAuth sign-in, which redirects here
		if has_request_context() and ERROR_KEY in session:
			self.error = session.pop(ERROR_KEY)


	def render(self):

		user = current_user()
		if user is not None:
			return [t.p() ["Signed in as ", t.strong() [_display_name(user)]]]

		return [
			t.form(on_submit=self.submit) [
				_error(self.error),
				t.label() [
					"Email",
					t.input(type="email", name="email", value=self.email, required=True, autocomplete="email"),
				],
				t.label() [
					"Password",
					t.input(type="password", name="password", required=True, autocomplete="current-password"),
				],
				t.button(type="submit") ["Log in"],
			],
			OAuthButton("github"),
			OAuthButton("google"),
		]


	def submit(self, event):

		self.email = normalize_email(_field(event, "email"))

		try:
			login(self.email, _field(event, "password"))
		except AccountError as error:
			self.error = str(error)
			return

		self.error = None
		if self.next_url:
			redirect(self.next_url)


class SignupForm(t.div):
	"""Name, email and password. Signs the new user in, then redirects to ?next= if given."""

	error = State(None)
	email = State("")
	name = State("")


	def init(self):

		self.next_url = _next_from_request()


	def render(self):

		user = current_user()
		if user is not None:
			return [t.p() ["Signed in as ", t.strong() [_display_name(user)]]]

		return [
			t.form(on_submit=self.submit) [
				_error(self.error),
				t.label() [
					"Name",
					t.input(name="name", value=self.name, autocomplete="name"),
				],
				t.label() [
					"Email",
					t.input(type="email", name="email", value=self.email, required=True, autocomplete="email"),
				],
				t.label() [
					"Password",
					t.input(type="password", name="password", required=True, minlength=MIN_PASSWORD_LENGTH, autocomplete="new-password"),
				],
				t.button(type="submit") ["Sign up"],
			],
			OAuthButton("github"),
			OAuthButton("google"),
		]


	def submit(self, event):

		self.name = _field(event, "name").strip()
		self.email = normalize_email(_field(event, "email"))

		try:
			user = create_user(self.email, _field(event, "password"), self.name)
			_sign_in(user["_id"])
		except AccountError as error:
			self.error = str(error)
			return

		self.error = None
		if self.next_url:
			redirect(self.next_url)


def _error(message):

	if not message:
		return ""

	return t.p(class_="error", role="alert") [message]


class LogoutButton(t.button):
	"""Logs out on click. Components showing current_user() re-render; other tabs of the same
	browser notice on their next page load."""


	def init(self):

		self.configure(type="button", on_click=self.logout)
		self.set_children(["Log out"])


	def logout(self):

		logout()


class UserMenu(t.div):
	"""Shows "Signed in as …" and a logout button, or links to log in and sign up."""


	def init(self):

		self.next_url = None
		if has_request_context() and request.path not in (login_url(), signup_url()):
			self.next_url = request.full_path.rstrip("?")


	def render(self):

		user = current_user()
		if user is not None:
			return [
				t.span() ["Signed in as ", t.strong() [_display_name(user)]],
				" ",
				LogoutButton(),
			]

		query = ""
		if self.next_url:
			query = "?" + urllib.parse.urlencode({"next": self.next_url})

		return [
			t.a(href=login_url() + query) ["Log in"],
			" ",
			t.a(href=signup_url() + query) ["Sign up"],
		]
