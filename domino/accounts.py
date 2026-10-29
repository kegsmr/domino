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
import hashlib
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
import itsdangerous
from flask import current_app, has_app_context, has_request_context, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from . import forms, mail, mongo
from . import tags as t
from .core import DEFAULT_PAGE, SESSION_USER_KEY, Page, redirect
from .reactive import Collection, State
from .util import is_local_url, urlopen


log = logging.getLogger(__name__)

# Server-side only: render fields from it, never whole documents (they hold password hashes)
users = Collection("users")

MIN_PASSWORD_LENGTH = 8

# Hashing a huge "password" is slow, so longer ones are refused before hashing
MAX_PASSWORD_LENGTH = 1024

# No characters that separate or quote addresses in a To: header ("a,b@c.d" is two addresses).
# Domain labels can't hold dots, so matching takes linear time (no backtracking over "a.a.a...")
EMAIL_PATTERN = re.compile(r"^[^@\s,;:<>()\[\]\\\"]+@(?:[^@\s.,;:<>()\[\]\\\"]+\.)+[^@\s.,;:<>()\[\]\\\"]+\Z")

WRONG_LOGIN = "Wrong email or password"
TOO_MANY_EMAILS = "Too many emails sent. Try again in a few minutes."
INVALID_LINK = "This link is invalid or has expired."

# Each kind of token is signed with a salt of its own, so one can't be used as another
RESET_SALT = "domino.accounts.reset-password"
VERIFY_SALT = "domino.accounts.verify-email"

STATE_KEY = "domino_oauth_state"
NEXT_KEY = "domino_oauth_next"
ERROR_KEY = "domino_accounts_error"


class AccountError(ValueError):
	"""Something the user can fix; str(error) is a message to show them. `field` is the form
	field it's about ("email", "password"), if any."""


	def __init__(self, message, field=None):

		super().__init__(message)
		self.field = field


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


def forgot_url():

	return settings().get("forgot_url") or "/forgot-password"


def reset_url():

	return settings().get("reset_url") or "/reset-password"


def verify_url():

	return settings().get("verify_url") or "/verify-email"


def check_email_url():

	return settings().get("check_email_url") or "/check-email"


def _with_query(url, **params):
	"""`url` with `params` (those that aren't None) added to its query string."""

	params = {key: value for key, value in params.items() if value is not None}
	if not params:
		return url

	separator = "?"
	if "?" in url:
		separator = "&"

	return url + separator + urllib.parse.urlencode(params)


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
	user["verified"] = user.get("verified") is True

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
	if len(email) > 254 or not EMAIL_PATTERN.match(email):
		raise AccountError("Enter a valid email address", "email")
	_check_new_password(password)
	if _users().find_one({"email": email}):
		raise AccountError("An account with this email already exists", "email")

	name = str(name or "").strip() or None
	user_id = _insert_user({
		"email": email,
		"password_hash": generate_password_hash(password),
		"name": name,
		"created": datetime.now(timezone.utc),
		"services": {},
		"verified": False,
	})

	return _public(_users().find_one({"_id": user_id}))


def _check_new_password(password):

	if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
		raise AccountError(f"Use a password of at least {MIN_PASSWORD_LENGTH} characters", "password")
	if len(password) > MAX_PASSWORD_LENGTH:
		raise AccountError(f"Use a password of at most {MAX_PASSWORD_LENGTH} characters", "password")


def set_password(user_id, password):
	"""Give the user a new password. Reset links sent before it stop working. Browsers signed
	in elsewhere stay signed in: sessions are cookies, so there's no list of them to end."""

	if not _store_password({"_id": user_id}, password):
		raise AccountError("There's no such user")


def _store_password(query, password, changes=None):
	"""Set the password of the user matching `query`. Returns whether there was one."""

	_check_new_password(password)

	changes = dict(changes or {}, password_hash=generate_password_hash(password))
	if not _users().update(query, {"$set": changes}):
		return False

	# A new password ends a lockout
	user = _users().find_one({"_id": query["_id"]})
	if user is not None and user.get("email"):
		with _failures_lock:
			_failures.pop(f"email:{user['email']}", None)

	return True


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

# Emails sent (password resets, verification links) per address, user and IP address
_mailed = {}


def _recent_failures(key, window, now, table=_failures):
	"""Failures for `key` in the last `window` seconds. Call with _failures_lock held."""

	times = [moment for moment in table.get(key, ()) if moment > now - window]
	if times:
		table[key] = times
	else:
		table.pop(key, None)

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


def _locked(limits, window, table=_failures):

	now = time.monotonic()
	with _failures_lock:
		return any(len(_recent_failures(key, window, now, table)) >= limit for key, limit in limits)


def _record_failure(limits, window, table=_failures):

	now = time.monotonic()
	with _failures_lock:
		# Forget old entries now and then, so the table can't grow without bound
		if len(table) > 10000:
			for key in list(table):
				_recent_failures(key, window, now, table)
		for key, _ in limits:
			table.setdefault(key, []).append(now)


def _may_send_email(key):
	"""Whether another email may go out for `key` (an address or a user), counting this one.
	Like failed logins: at most accounts.max_emails (default 3) per key and four times as many
	per IP address in accounts.email_window_seconds (default 15 minutes)."""

	config = settings()
	count = int(config.get("max_emails") or 3)
	window = float(config.get("email_window_seconds") or 900)

	limits = [(key, count)]
	if has_request_context() and request.remote_addr:
		limits.append((f"ip:{request.remote_addr}", count * 4))

	if _locked(limits, window, _mailed):
		return False

	_record_failure(limits, window, _mailed)

	return True


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


def login_required(function=None, *, verified=False):
	"""For route functions and page() functions: visitors who aren't signed in are sent to the login page
	(the accounts.login_url setting, default /login) with ?next= pointing back here.

	@login_required(verified=True) also sends users who haven't verified their email to the
	accounts.check_email_url page (default /check-email), which can send the link again."""

	if function is None:
		return functools.partial(login_required, verified=verified)

	@functools.wraps(function)
	def wrapper(*args, **kwargs):

		user = current_user()
		if user is None:
			return flask.redirect(_with_query(login_url(), next=request.full_path.rstrip("?")))
		if verified and not user["verified"]:
			return flask.redirect(_with_query(check_email_url(), next=request.full_path.rstrip("?")))

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


# Links in emails: password resets and email verification. The tokens in them are signed with
# the secret_key (and a salt per purpose), so they can't be forged, and carry the time they were
# made, so they expire


def _clock():

	# Tokens' timestamps; tests move it forward to expire them
	return time.time()


class _Signer(itsdangerous.TimestampSigner):


	def get_timestamp(self):

		return int(_clock())


def _secret_key():

	if has_request_context():
		_ensure_secret_key()

	app = _app()
	if app is None or not app.secret_key:
		raise AccountsConfigError("Links in emails are signed with the secret_key setting; set it (or DOMINO_SECRET_KEY)")

	return app.secret_key


def _serializer(salt):

	return itsdangerous.URLSafeTimedSerializer(_secret_key(), salt=salt, signer=_Signer)


def _load_token(salt, token, max_age):
	"""The data signed into `token`, or None if it's forged, altered or older than `max_age` seconds."""

	if not isinstance(token, str) or not token or len(token) > 1000:
		return None

	try:
		data = _serializer(salt).loads(token, max_age=max_age)
	except itsdangerous.BadData:
		return None

	if not isinstance(data, dict):
		return None

	return data


def _password_stamp(user):
	"""Changes whenever the user's password (or email) does. In a reset token it makes the token
	single-use: once the password is reset (or changed) the token no longer matches. A link sent
	to an address the account has since stopped using stops working too."""

	key = _secret_key()
	if isinstance(key, str):
		key = key.encode("utf-8")

	stored = str(user.get("password_hash") or "").encode("utf-8")
	email = str(user.get("email") or "").encode("utf-8")

	return hmac.new(key, b"password:" + stored + b"\0" + email, hashlib.sha256).hexdigest()[:32]


def absolute_url(path):
	"""`path` as a full URL for a link in an email: on the public_url setting (e.g.
	"https://example.com"), or else on the URL the current request came to."""

	app = _app()
	base = None
	if app is not None:
		base = app.settings.get("public_url")
	if base:
		return str(base).rstrip("/") + path

	if not has_request_context():
		raise AccountsConfigError("Set the public_url setting (e.g. \"https://example.com\") to put links in emails sent outside a request")

	# The host comes from the request's Host header, which the sender chooses: a reset link for
	# someone else's account, asked for with a forged one, would point to the sender's site and
	# hand them its token when clicked. So emails that really go out need public_url
	if not app.debug and mail.backend_name() == "smtp":
		raise AccountsConfigError(
			"Set the public_url setting (e.g. \"https://example.com\", or DOMINO_PUBLIC_URL) for links in "
			"emails: without it they'd use the Host header of the request, which the sender can forge."
		)

	return request.url_root.rstrip("/") + path


def send_reset_email(user):
	"""Email the user a link to the reset page (the accounts.reset_url setting, default
	/reset-password). It works once, for accounts.reset_link_seconds (default an hour)."""

	token = _serializer(RESET_SALT).dumps({"user": user["_id"], "stamp": _password_stamp(user)})
	link = absolute_url(_with_query(reset_url(), token=token))
	minutes = round(float(settings().get("reset_link_seconds") or 3600) / 60)

	return mail.send(user["email"], "Reset your password", (
		"Someone (hopefully you) asked to reset the password of your account.\n\n"
		f"To choose a new password, open this link within {minutes} minutes:\n\n"
		f"{link}\n\n"
		"If you didn't ask for this, ignore this email; your password stays as it is.\n"
	))


def _reset_user(token):
	"""The user a reset token is for, or None if it isn't valid (any more)."""

	data = _load_token(RESET_SALT, token, float(settings().get("reset_link_seconds") or 3600))
	if data is None:
		return None

	user = _users().find_one({"_id": data.get("user")})
	stamp = str(data.get("stamp")).encode("utf-8")
	if user is None or not hmac.compare_digest(stamp, _password_stamp(user).encode("utf-8")):
		return None

	return user


def reset_password(token, password):
	"""Set a new password with a token from a reset email, and return the user. Raises
	AccountError if the token is invalid, expired or already used, or the password won't do."""

	user = _reset_user(token)
	if user is None:
		raise AccountError(INVALID_LINK)

	# Only while the password is still the one the token was made for, so of two submits of
	# the same link at once only one gets through. The link arrived by email, so the email is
	# the user's: they're verified too
	query = {"_id": user["_id"], "password_hash": user.get("password_hash")}
	if not _store_password(query, password, {"verified": True}):
		raise AccountError(INVALID_LINK)

	return _public(_users().find_one({"_id": user["_id"]}))


def send_verification_email(user, next_url=None):
	"""Email the user a link to the verify page (the accounts.verify_url setting, default
	/verify-email), which marks them verified. It works for accounts.verify_link_seconds
	(default 3 days). `next_url` is where its Continue link goes."""

	token = _serializer(VERIFY_SALT).dumps({"user": user["_id"], "email": user["email"]})
	link = absolute_url(_with_query(verify_url(), token=token, next=safe_next(next_url)))

	return mail.send(user["email"], "Verify your email", (
		"Please confirm that this is your email address by opening this link:\n\n"
		f"{link}\n\n"
		"If you didn't sign up, ignore this email.\n"
	))


def verify_email(token):
	"""Mark the user a verification token is for as verified, and return them (None if the
	token is invalid or expired). Opening the link again does no harm."""

	data = _load_token(VERIFY_SALT, token, float(settings().get("verify_link_seconds") or 3 * 24 * 3600))
	if data is None:
		return None

	# Only for the address the link was sent to
	user = _users().find_one({"_id": data.get("user")})
	if user is None or not user.get("email") or user.get("email") != data.get("email"):
		return None

	if not user.get("verified"):
		_users().update({"_id": user["_id"]}, {"$set": {"verified": True}})

	return _public(_users().find_one({"_id": user["_id"]}))


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
		with urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=10) as response:
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
		# The provider has verified the email, so the user has too
		_users().update({"_id": existing["_id"]}, {"$set": {field: service, "verified": True}})
		return existing

	document = {
		"password_hash": None,
		"name": profile.get("name"),
		"created": datetime.now(timezone.utc),
		"services": {provider: service},
		"verified": False,
	}
	if email and profile.get("verified"):
		document["email"] = email
		document["verified"] = True

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

	# On public_url when it's set, rather than on the request's (forgeable) Host header
	callback = flask.url_for("domino_oauth", provider=provider, action="callback", _external=True)
	base = (_app().settings.get("public_url") or "") if _app() is not None else ""
	if base:
		callback = str(base).rstrip("/") + flask.url_for("domino_oauth", provider=provider, action="callback")

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


# Ready-made components. Plain HTML; each has its class name (LoginForm, ...) for styling.
# The forms are domino.forms Forms, so their labels, messages and layout can be changed the
# same way (subclass one, or pass submit_text=...)


def _display_name(user):

	return user.get("name") or user.get("email") or "user"


def _signed_in(user):

	return t.p() ["Signed in as ", t.strong() [_display_name(user)]]


class AccountEmail(forms.Text):
	"""An email address, lowercased (also when the form shows it again after an error). It
	isn't checked here: create_user() does that, and login() just doesn't find a bad one."""

	input_type = "email"


	def raw(self, form):

		return normalize_email(super().raw(form))


def _new_password(label):

	return forms.Password(
		label,
		required=True,
		min_length=MIN_PASSWORD_LENGTH,
		autocomplete="new-password",
		messages={"min_length": "Use a password of at least {min_length} characters"}
	)


def _show_error(form, error):
	"""An AccountError next to its field, or above the form."""

	field = error.field
	if field not in type(form)._fields:
		field = None

	form.error(field, str(error))


def _passwords_match(form, data):
	"""validate() of the forms with a new password and its confirmation."""

	if data.password != data.confirm:
		raise forms.ValidationError("The passwords don't match", field="confirm")


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


class LoginForm(forms.Form):
	"""Email and password, with errors shown inline. Redirects to ?next= after logging in.
	Shows "Forgot your password?" when the accounts.forgot_url setting is set."""

	email = AccountEmail("Email", required=True, autocomplete="email")
	password = forms.Password("Password", required=True, autocomplete="current-password")

	submit_text = "Log in"


	def init(self):

		self.next_url = _next_from_request()

		# Set by a failed OAuth sign-in, which redirects here
		if has_request_context() and ERROR_KEY in session:
			self.errors = {None: session.pop(ERROR_KEY)}


	def render(self):

		user = current_user()
		if user is not None:
			return [_signed_in(user)]

		parts = super().render()
		if settings().get("forgot_url"):
			parts.append(t.a(class_="forgot-password", href=forgot_url()) ["Forgot your password?"])

		return parts + [OAuthButton("github"), OAuthButton("google")]


	def submitted(self, data):

		try:
			login(data.email, data.password)
		except AccountError as error:
			self.error(None, str(error))
			return

		if self.next_url:
			redirect(self.next_url)


class SignupForm(forms.Form):
	"""Name, email and password. Signs the new user in, then redirects to ?next= if given.
	With the accounts.verify_email setting, also emails them a link to verify their email."""

	name = forms.Text("Name", autocomplete="name")
	email = AccountEmail("Email", required=True, autocomplete="email")
	password = _new_password("Password")

	submit_text = "Sign up"


	def init(self):

		self.next_url = _next_from_request()


	def render(self):

		user = current_user()
		if user is not None:
			return [_signed_in(user)]

		return super().render() + [OAuthButton("github"), OAuthButton("google")]


	def submitted(self, data):

		try:
			user = create_user(data.email, data.password, data.name)
			_sign_in(user["_id"])
		except AccountError as error:
			_show_error(self, error)
			return

		if settings().get("verify_email"):
			send_verification_email(user, self.next_url)

		if self.next_url:
			redirect(self.next_url)


class ForgotPasswordForm(forms.Form):
	"""Asks for an email and sends a link to reset the password (see send_reset_email). It says
	the same whether or not there's an account with that email, so it can't be used to find out."""

	email = AccountEmail("Email", required=True, autocomplete="email")

	submit_text = "Email me a link"

	sent = State(False)


	def render(self):

		if self.sent:
			return [t.p(role="status") ["If an account exists for that email, we've emailed a link to reset your password."]]

		return super().render()


	def submitted(self, data):

		# Counted for any address, so this message doesn't tell which have accounts either
		if not _may_send_email(f"reset:{data.email}"):
			self.error(None, TOO_MANY_EMAILS)
			return

		user = None
		if data.email:
			user = _users().find_one({"email": data.email})
		if user is not None:
			send_reset_email(user)

		self.sent = True


class ResetPasswordForm(forms.Form):
	"""The page a reset link opens: a new password (twice), for the user in its ?token=."""

	password = _new_password("New password")
	confirm = forms.Password("Confirm new password", required=True, autocomplete="new-password")

	submit_text = "Change password"

	validate = _passwords_match

	done = State(False)
	invalid = State(False)


	def init(self):

		self.token = ""
		if has_request_context():
			self.token = request.args.get("token", "")

		self.invalid = _reset_user(self.token) is None


	def render(self):

		if self.done:
			return [
				t.p(role="status") ["Your password has been changed. "],
				t.a(href=login_url()) ["Log in"],
			]

		if self.invalid:
			return [
				t.p(class_="form-error", role="alert") [INVALID_LINK],
				t.a(href=forgot_url()) ["Get a new link"],
			]

		return super().render()


	def submitted(self, data):

		try:
			reset_password(self.token, data.password)
		except AccountError as error:
			if str(error) == INVALID_LINK:
				self.invalid = True
				return
			_show_error(self, error)
			return

		self.done = True


class ChangePasswordForm(forms.Form):
	"""For a signed-in user: their current password and a new one (twice). Other browsers
	signed in to the account stay signed in."""

	current = forms.Password("Current password", required=True, autocomplete="current-password")
	password = _new_password("New password")
	confirm = forms.Password("Confirm new password", required=True, autocomplete="new-password")

	submit_text = "Change password"

	validate = _passwords_match

	changed = State(False)


	def render(self):

		if current_user() is None:
			return [t.p() ["Log in to change your password."]]

		parts = super().render()
		if self.changed and not self.errors:
			parts.insert(0, t.p(class_="success", role="status") ["Your password has been changed."])

		return parts


	def submitted(self, data):

		self.changed = False

		user = None
		uid = user_id()
		if uid is not None:
			user = _users().find_one({"_id": uid})
		if user is None:
			self.error(None, "Log in to change your password.")
			return

		# Guessing the current password counts as failed logins, so it's locked out the same way
		limits, window = _limits(user.get("email") or uid)
		if _locked(limits, window):
			self.error(None, "Too many failed attempts. Try again in a minute.")
			return
		if not _check_password(user, data.current[:MAX_PASSWORD_LENGTH]):
			_record_failure(limits, window)
			self.error("current", "Wrong password")
			return

		try:
			set_password(uid, data.password)
		except AccountError as error:
			_show_error(self, error)
			return

		self.changed = True


class VerifyEmail(t.div):
	"""The page a verification link opens: marks the user in its ?token= as verified."""


	def init(self):

		self.next_url = _next_from_request()

		token = ""
		if has_request_context():
			token = request.args.get("token", "")

		self.verified = verify_email(token) is not None


	def render(self):

		if self.verified:
			return [
				t.p(role="status") ["Your email is verified. "],
				t.a(href=self.next_url or "/") ["Continue"],
			]

		return [
			t.p(class_="error", role="alert") [INVALID_LINK],
			t.a(href=_with_query(check_email_url(), next=self.next_url)) ["Get a new link"],
		]


class CheckEmail(t.div):
	"""The page @login_required(verified=True) sends unverified users to: asks them to click
	the link in their email, with a button that sends it again (rate-limited)."""

	notice = State(None)


	def init(self):

		self.next_url = _next_from_request()


	def render(self):

		user = current_user()
		if user is None:
			return [t.p() [t.a(href=_with_query(login_url(), next=self.next_url)) ["Log in"], " to verify your email."]]

		if user["verified"]:
			return [
				t.p() ["Your email is verified. "],
				t.a(href=self.next_url or "/") ["Continue"],
			]

		if not user.get("email"):
			return [t.p() ["Your account has no email address to verify."]]

		return [
			t.p() ["We've emailed a link to ", t.strong() [user["email"]], ". Open it to verify your email."],
			t.button(type="button", on_click=self.resend) ["Send it again"],
			t.p(role="status") [self.notice] if self.notice else "",
		]


	def resend(self):

		user = current_user()
		if user is None or user["verified"] or not user.get("email"):
			return

		if not _may_send_email(f"verify:{user['_id']}"):
			self.notice = TOO_MANY_EMAILS
			return

		send_verification_email(user, self.next_url)
		self.notice = "Sent. Check your inbox."


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
		# Not back to the account pages themselves (nor a reset link's token)
		pages = [login_url(), signup_url(), forgot_url(), reset_url()]
		if has_request_context() and request.path not in [url.split("?")[0] for url in pages]:
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
