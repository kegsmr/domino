import logging
import re
import time
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest

import domino
import domino.tags as t
from domino import Collection, Domino, accounts, wait
from domino.components import Document


PASSWORD = "correct horse"


@pytest.fixture(params=["memory", pytest.param("mongo", marks=pytest.mark.mongo)])
def users(request, monkeypatch):

	# The same tests against an in-memory collection and against MongoDB (with its indexes)
	collection = Collection()
	if request.param == "mongo":
		collection = Collection(f"users_{uuid.uuid4().hex[:8]}")

	monkeypatch.setattr(accounts, "users", collection)
	accounts._failures.clear()
	accounts._mailed.clear()

	return collection


def make_app(**settings):

	app = Domino(__name__)
	app.secret_key = "test secret"
	app.settings["accounts"] = settings

	@app.route("/")
	def index():
		return Document() [
			accounts.UserMenu(),
			accounts.LoginForm()
		]

	@app.route("/signup")
	def signup():
		return Document() [
			accounts.SignupForm()
		]

	@app.route("/private")
	@accounts.login_required
	def private():
		return Document() [
			t.p() [f"Hello {accounts.current_user()['email']}"]
		]

	return app


def load(client, path="/"):
	"""The page id and its event ids by event type ("submit", "click")."""

	html = client.get(path).get_data(as_text=True)
	page_id = re.search(r'data-domino-page="([^"]+)"', html).group(1)
	events = {}
	for event_id in re.findall(r'data-event-id="([^"]+)"', html):
		events[event_id.rsplit("-", 1)[-1]] = event_id

	return page_id, events, html


def send(client, page_id, event_id, form=None):

	return client.post("/_domino/events", json={"page_id": page_id, "event_id": event_id, "data": {"form": form or {}}})


def log_in(client, email="ada@example.com", password=PASSWORD, path="/"):

	page_id, events, _ = load(client, path)

	return send(client, page_id, events["submit"], {"email": email, "password": password})


def rendered(app, page_id, response):
	"""The HTML the browser got for this page: the event response and what was pushed after."""

	wait()
	page = app.page_store.pages[page_id]
	html = [response.get_json().get("html") or ""]
	html.extend(update["html"] for update in page.updates.values())

	return "\n".join(html)


def test_create_user_normalizes_email_and_hides_the_hash(users):

	user = accounts.create_user("  Ada@Example.COM ", PASSWORD, "Ada")

	assert user["email"] == "ada@example.com"
	assert user["name"] == "Ada"
	assert "password_hash" not in user

	stored = users.find_one({"_id": user["_id"]})
	assert stored["password_hash"].split(":")[0] in ("scrypt", "pbkdf2")
	assert PASSWORD not in stored["password_hash"]


@pytest.mark.parametrize("email, password, message", [
	("not-an-email", PASSWORD, "valid email"),
	("ada@example", PASSWORD, "valid email"),
	("ada@example.com", "short", "at least 8"),
	("ada@example.com", "x" * 2000, "at most"),
])
def test_create_user_rejects_weak_input(users, email, password, message):

	with pytest.raises(accounts.AccountError, match=message):
		accounts.create_user(email, password)

	assert users.count() == 0


def test_create_user_rejects_duplicate_email(users):

	accounts.create_user("ada@example.com", PASSWORD)

	with pytest.raises(accounts.AccountError, match="already exists"):
		accounts.create_user("ADA@example.com", PASSWORD)


@pytest.mark.mongo
def test_unique_index_catches_a_duplicate_that_slipped_past_the_check(monkeypatch):

	monkeypatch.setattr(accounts, "users", Collection(f"users_{uuid.uuid4().hex[:8]}"))

	# As if two sign-ups had passed the find_one() check at the same moment
	accounts._insert_user({"email": "ada@example.com", "password_hash": None})
	with pytest.raises(accounts.AccountError, match="already exists"):
		accounts._insert_user({"email": "ada@example.com", "password_hash": None})

	indexes = accounts.users.store().collection.index_information()
	assert indexes["email_1"]["unique"] and indexes["services.github.id_1"]["sparse"]


def test_wrong_password_and_unknown_email_get_the_same_message(users):

	app = make_app()
	accounts.create_user("ada@example.com", PASSWORD)

	messages = []
	for email, password in [("ada@example.com", "wrong password"), ("nobody@example.com", PASSWORD)]:
		with app.test_request_context():
			with pytest.raises(accounts.AccountError) as error:
				accounts.login(email, password)
		messages.append(str(error.value))

	assert messages == ["Wrong email or password"] * 2

	# The form shows it inline and keeps the typed email, not the password
	client = app.test_client()
	page_id, _, _ = load(client)
	html = log_in(client, "Ada@Example.com", "wrong password").get_json()["html"]
	assert 'role="alert"' in html and "Wrong email or password" in html
	assert 'value="ada@example.com"' in html
	assert "wrong password" not in html


def test_repeated_failures_lock_the_email_out_for_a_while(users):

	app = make_app(max_attempts=3, lockout_seconds=0.5)
	accounts.create_user("ada@example.com", PASSWORD)
	accounts.create_user("bob@example.com", PASSWORD)

	with app.test_request_context():
		for _ in range(3):
			with pytest.raises(accounts.AccountError, match="Wrong email"):
				accounts.login("ada@example.com", "wrong password")

		# Even the right password is refused while locked
		with pytest.raises(accounts.AccountError, match="Too many"):
			accounts.login("ada@example.com", PASSWORD)

		# Other emails aren't affected
		assert accounts.login("bob@example.com", PASSWORD)["email"] == "bob@example.com"

	time.sleep(0.6)
	with app.test_request_context():
		assert accounts.login("ada@example.com", PASSWORD)["email"] == "ada@example.com"


def test_failures_from_one_address_lock_it_out_across_emails(users):

	app = make_app(max_attempts=2, lockout_seconds=5)
	accounts.create_user("ada@example.com", PASSWORD)

	# Two failures each for four emails: no email is locked, but the address is (2 x 4)
	with app.test_request_context(environ_base={"REMOTE_ADDR": "203.0.113.9"}):
		for number in range(4):
			for _ in range(2):
				with pytest.raises(accounts.AccountError, match="Wrong email"):
					accounts.login(f"guess{number}@example.com", "wrong password")
		with pytest.raises(accounts.AccountError, match="Too many"):
			accounts.login("ada@example.com", PASSWORD)

	with app.test_request_context(environ_base={"REMOTE_ADDR": "198.51.100.1"}):
		assert accounts.login("ada@example.com", PASSWORD)


def test_login_starts_a_fresh_session(users):

	app = make_app()
	accounts.create_user("ada@example.com", PASSWORD)
	client = app.test_client()

	with client.session_transaction() as session:
		session["planted"] = "by someone else"

	response = log_in(client)
	cookie = response.headers["Set-Cookie"]

	with client.session_transaction() as session:
		assert "planted" not in session
		assert session[domino.SESSION_USER_KEY] == accounts.users.find_one()["_id"]
		assert session.permanent

	# HttpOnly and SameSite=Lax always; Secure outside debug
	assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Secure" in cookie


def test_cookie_is_not_secure_while_debugging_or_when_turned_off(users):

	accounts.create_user("ada@example.com", PASSWORD)

	app = make_app()
	app.debug = True
	assert "Secure" not in log_in(app.test_client()).headers["Set-Cookie"]

	app = make_app()
	app.config["DOMINO_SECURE_COOKIES"] = False
	assert "Secure" not in log_in(app.test_client()).headers["Set-Cookie"]


def test_logging_in_re_renders_the_user_menu_on_that_page_only(users):

	app = make_app()
	accounts.create_user("ada@example.com", PASSWORD, "Ada")
	client = app.test_client()
	other_page, _, _ = load(app.test_client())

	page_id, events, html = load(client)
	assert "Log in" in html and "Signed in as" not in html

	response = send(client, page_id, events["submit"], {"email": "ada@example.com", "password": PASSWORD})
	html = rendered(app, page_id, response)

	# The menu and the form both read current_user(); one comes back in the response and the
	# other is pushed, rendered outside the request from the page's user
	assert re.search(r'class="UserMenu".*?Signed in as\s*<strong>\s*Ada', html, re.S)
	assert re.search(r'class="LoginForm Form".*?Signed in as', html, re.S)
	assert app.page_store.pages[other_page].updates == {}

	# A new page load reads the user from the session cookie
	page_id, events, html = load(client)
	assert "Signed in as" in html and "Log out" in html

	response = send(client, page_id, events["click"])
	html = rendered(app, page_id, response)
	assert re.search(r'class="UserMenu".*?Log in', html, re.S)
	with client.session_transaction() as session:
		assert domino.SESSION_USER_KEY not in session
	assert "Signed in as" not in load(client)[2]


def test_sign_up_form_creates_the_user_and_signs_in(users):

	app = make_app()
	client = app.test_client()

	page_id, events, _ = load(client, "/signup?next=/private")
	html = send(client, page_id, events["submit"], {"name": "Ada", "email": "ada@example.com", "password": "short"}).get_json()["html"]
	assert "at least 8" in html and 'value="ada@example.com"' in html and 'value="Ada"' in html

	response = send(client, page_id, events["submit"], {"name": "Ada", "email": "ada@example.com", "password": PASSWORD})
	assert response.get_json()["redirect"] == "/private"
	assert client.get("/private").get_data(as_text=True).count("Hello ada@example.com") == 1


def test_login_required_redirects_to_login_with_next(users):

	app = make_app()
	accounts.create_user("ada@example.com", PASSWORD)
	client = app.test_client()

	response = client.get("/private?tab=notes")
	assert response.status_code == 302
	assert response.headers["Location"] == "/login?next=%2Fprivate%3Ftab%3Dnotes"

	app.settings["accounts"] = {"login_url": "/account?view=login"}
	assert client.get("/private").headers["Location"] == "/account?view=login&next=%2Fprivate"

	# The login form sends the user back there
	response = log_in(client, path="/?next=%2Fprivate%3Ftab%3Dnotes")
	assert response.get_json()["redirect"] == "/private?tab=notes"
	assert client.get("/private").status_code == 200


@pytest.mark.parametrize("next_url", ["//evil.com", "https://evil.com/", "/\\evil.com", "/\t/evil.com", "javascript:alert(1)"])
def test_login_ignores_next_pointing_at_another_site(users, next_url):

	app = make_app()
	accounts.create_user("ada@example.com", PASSWORD)
	client = app.test_client()

	page_id, events, _ = load(client, "/?" + "next=" + next_url.replace("\t", "%09"))
	response = send(client, page_id, events["submit"], {"email": "ada@example.com", "password": PASSWORD})

	assert response.status_code == 200
	assert "redirect" not in response.get_json()


@pytest.mark.parametrize("url, local", [
	("/", True),
	("/private?tab=notes#top", True),
	("/a//b", True),
	("//evil.com", False),
	("///evil.com", False),
	("/\\evil.com", False),
	("/\t/evil.com", False),
	("/\n/evil.com", False),
	("https://evil.com", False),
	("http:/evil.com", False),
	("evil.com", False),
	("", False),
	(None, False),
])
def test_is_local_url(url, local):

	assert domino.is_local_url(url) is local


def test_redirect_from_an_event_handler():

	class Go(t.div):

		def render(self):
			return [
				t.button(class_="ok", on_click=self.ok) ["Go"],
				t.button(class_="evil", on_click=self.evil) ["Evil"],
			]

		def ok(self):
			domino.redirect("/somewhere?x=1")

		def evil(self):
			domino.redirect("https://evil.com/")

	app = Domino(__name__)

	@app.route("/")
	def index():
		return Document() [Go()]

	client = app.test_client()
	html = client.get("/").get_data(as_text=True)
	page_id = re.search(r'data-domino-page="([^"]+)"', html).group(1)
	ok, evil = re.findall(r'data-event-id="([^"]+)"', html)

	assert send(client, page_id, ok).get_json()["redirect"] == "/somewhere?x=1"
	assert send(client, page_id, evil).status_code == 500

	# Outside an event handler it's Flask's redirect
	with app.test_request_context():
		response = domino.redirect("https://example.com/")
	assert response.status_code == 302 and response.headers["Location"] == "https://example.com/"


def test_secret_key_is_made_up_while_debugging(users, caplog):

	app = make_app()
	app.secret_key = None
	app.debug = True
	accounts.create_user("ada@example.com", PASSWORD)
	client = app.test_client()

	with caplog.at_level(logging.WARNING, logger="domino.accounts"):
		assert client.get("/").status_code == 200

	assert app.secret_key
	assert "won't survive a restart" in caplog.text
	assert log_in(client).status_code == 200
	assert "Signed in as" in load(client)[2]


def test_secret_key_is_required_outside_debug(users, monkeypatch):

	app = make_app()
	app.secret_key = None

	with app.test_request_context():
		with pytest.raises(accounts.AccountsConfigError, match="secret_key"):
			accounts.current_user()
		with pytest.raises(accounts.AccountsConfigError, match="DOMINO_SECRET_KEY"):
			accounts.login("ada@example.com", PASSWORD)

	monkeypatch.setenv("DOMINO_SECRET_KEY", "from the environment")
	assert Domino(__name__).secret_key == "from the environment"


@pytest.mark.parametrize("content_type, body", [
	("text/plain", '{"page_id": "x", "event_id": "y"}'),
	("application/x-www-form-urlencoded", "page_id=x&event_id=y"),
	("multipart/form-data; boundary=x", "--x--"),
	(None, ""),
])
def test_event_endpoint_rejects_anything_but_json(content_type, body):

	app = make_app()
	client = app.test_client()
	page_id, events, _ = load(client)

	response = client.post("/_domino/events", data=body, content_type=content_type)

	assert response.status_code == 415
	assert send(client, page_id, events["submit"], {}).status_code == 200


# OAuth, against a fake provider


GITHUB = {"github": {"client_id": "id123", "client_secret": "shh"}}


class FakeProvider:


	def __init__(self, user, emails=None):

		self.user = user
		self.emails = emails or []
		self.requests = []


	def __call__(self, url, data=None, token=None):

		self.requests.append((url, data, token))
		if url.endswith("/access_token") or url.endswith("/token"):
			assert data["code"] == "the-code" and data["client_secret"]
			return {"access_token": "the-token", "token_type": "bearer"}
		assert token == "the-token"
		if url.endswith("/user/emails"):
			return self.emails
		return self.user


def github_user(id_=42, email="ada@example.com", verified=True):

	return FakeProvider(
		{"id": id_, "login": "ada", "name": "Ada Lovelace"},
		[{"email": "old@example.com", "primary": False, "verified": True}, {"email": email, "primary": True, "verified": verified}]
	)


def start_oauth(client, provider="github", next_url="/private"):

	response = client.get(f"/_domino/accounts/{provider}/login?next={next_url}")
	assert response.status_code == 302

	location = urlsplit(response.headers["Location"])
	query = {key: values[0] for key, values in parse_qs(location.query).items()}

	return location, query


def finish_oauth(client, state, provider="github"):

	return client.get(f"/_domino/accounts/{provider}/callback?code=the-code&state={state}")


def test_oauth_creates_a_user_and_signs_in(users, monkeypatch):

	fake = github_user()
	monkeypatch.setattr(accounts, "_fetch_json", fake)
	app = make_app(**GITHUB)
	client = app.test_client()

	location, query = start_oauth(client)
	assert location.netloc == "github.com"
	assert query["client_id"] == "id123" and query["scope"] == "read:user user:email"
	assert query["redirect_uri"] == "http://localhost/_domino/accounts/github/callback"
	assert len(query["state"]) > 30

	response = finish_oauth(client, query["state"])
	assert response.status_code == 302 and response.headers["Location"] == "/private"
	assert fake.requests[0][1]["redirect_uri"] == query["redirect_uri"]

	user = users.find_one({"services.github.id": "42"})
	assert user["email"] == "ada@example.com"
	assert user["name"] == "Ada Lovelace"
	assert user["password_hash"] is None
	assert "the-token" not in str(user)
	assert "Hello ada@example.com" in client.get("/private").get_data(as_text=True)

	# Signing in again finds the same user
	client = app.test_client()
	_, query = start_oauth(client)
	finish_oauth(client, query["state"])
	assert users.count() == 1


def test_oauth_links_to_an_existing_user_with_the_same_verified_email(users, monkeypatch):

	monkeypatch.setattr(accounts, "_fetch_json", github_user(email="ADA@example.com"))
	existing = accounts.create_user("ada@example.com", PASSWORD)
	client = make_app(**GITHUB).test_client()

	_, query = start_oauth(client)
	finish_oauth(client, query["state"])

	assert users.count() == 1
	assert users.find_one({"_id": existing["_id"]})["services"]["github"]["id"] == "42"
	with client.session_transaction() as session:
		assert session[domino.SESSION_USER_KEY] == existing["_id"]


def test_oauth_with_an_unverified_email_does_not_take_over_an_account(users, monkeypatch):

	monkeypatch.setattr(accounts, "_fetch_json", github_user(verified=False))
	accounts.create_user("ada@example.com", PASSWORD)
	client = make_app(**GITHUB).test_client()

	_, query = start_oauth(client)
	response = finish_oauth(client, query["state"])

	assert response.headers["Location"] == "/login"
	assert users.count() == 1 and "github" not in users.find_one()["services"]
	with client.session_transaction() as session:
		assert domino.SESSION_USER_KEY not in session

	# The login form shows why, once
	html = client.get("/").get_data(as_text=True)
	assert "already exists. Log in with your password." in html
	assert "already exists" not in client.get("/").get_data(as_text=True)


def test_oauth_rejects_a_state_mismatch(users, monkeypatch):

	fake = github_user()
	monkeypatch.setattr(accounts, "_fetch_json", fake)
	client = make_app(**GITHUB).test_client()

	start_oauth(client)
	assert finish_oauth(client, "forged-state").status_code == 400

	# The state is used up either way, and a callback nobody started is rejected too
	assert finish_oauth(client, "").status_code == 400
	assert make_app(**GITHUB).test_client().get("/_domino/accounts/github/callback?code=the-code&state=x").status_code == 400

	assert fake.requests == []
	assert users.count() == 0


def test_oauth_with_google(users, monkeypatch):

	fake = FakeProvider({"sub": "1234567890", "email": "ada@example.com", "email_verified": True, "name": "Ada"})
	monkeypatch.setattr(accounts, "_fetch_json", fake)
	client = make_app(google={"client_id": "gid", "client_secret": "gsecret"}).test_client()

	location, query = start_oauth(client, "google", "/")
	assert location.netloc == "accounts.google.com" and query["scope"] == "openid email profile"

	assert finish_oauth(client, query["state"], "google").headers["Location"] == "/"
	assert users.find_one({"services.google.id": "1234567890"})["email"] == "ada@example.com"


def test_oauth_provider_failure_returns_to_login(users, monkeypatch):

	def broken(url, data=None, token=None):
		raise accounts.OAuthError("connection refused")

	monkeypatch.setattr(accounts, "_fetch_json", broken)
	client = make_app(**GITHUB).test_client()

	_, query = start_oauth(client)
	assert finish_oauth(client, query["state"]).headers["Location"] == "/login"
	assert "Couldn&#39;t sign in with GitHub" in client.get("/").get_data(as_text=True)


def test_oauth_buttons_and_routes_only_exist_when_configured(users):

	client = make_app().test_client()
	assert "Continue with" not in client.get("/").get_data(as_text=True)
	assert client.get("/_domino/accounts/github/login").status_code == 404
	assert client.get("/_domino/accounts/nope/login").status_code == 404

	client = make_app(**GITHUB).test_client()
	html = client.get("/?next=/private").get_data(as_text=True)
	assert 'href="/_domino/accounts/github/login?next=%2Fprivate"' in html
	assert "Continue with GitHub" in html and "Google" not in html


def test_whole_flow_with_the_test_client(users):

	app = make_app()
	page = app.test_page("/private")

	# Not signed in: sent to the login page
	assert page.path == "/login"

	page = app.test_page("/signup")
	page.fill("input[name=email]", "ada@example.com")
	page.fill("input[name=password]", PASSWORD)
	page.submit()

	# Signed in, and domino.redirect() was followed (same cookies, like one browser)
	page.load("/private")
	assert page.text("p") == "Hello ada@example.com"

	page.load("/")
	page.click("button", text="Log out")
	page.load("/private")
	assert page.path == "/login"


# Password reset, email verification and changing the password


def make_full_app(**settings):

	app = make_app(**settings)

	@app.route("/forgot-password")
	def forgot_password():
		return Document() [accounts.ForgotPasswordForm()]

	@app.route("/reset-password")
	def reset_password():
		return Document() [accounts.ResetPasswordForm()]

	@app.route("/verify-email")
	def verify_email():
		return Document() [accounts.VerifyEmail()]

	@app.route("/check-email")
	def check_email():
		return Document() [accounts.CheckEmail()]

	@app.route("/account")
	@accounts.login_required
	def account():
		return Document() [accounts.ChangePasswordForm()]

	@app.route("/members")
	@accounts.login_required(verified=True)
	def members():
		return Document() [t.p(class_="members") [f"Welcome {accounts.current_user()['email']}"]]

	return app


def link_path(message):
	"""The path and query of the link in an email, to open with the test client."""

	(link,) = message.links
	parts = urlsplit(link)

	return f"{parts.path}?{parts.query}"


def ask_for_reset(app, email="ada@example.com"):

	page = app.test_page("/forgot-password")
	page.fill("input[name=email]", email)
	page.submit()

	return page


def choose_password(page, password, confirm=None):

	page.fill("input[name=password]", password)
	page.fill("input[name=confirm]", password if confirm is None else confirm)
	page.submit()

	return page


def can_log_in(app, password, email="ada@example.com"):

	with app.test_request_context():
		try:
			accounts.login(email, password)
		except accounts.AccountError:
			return False

	return True


def log_in_page(app, path):

	page = app.test_page("/")
	page.fill("input[name=email]", "ada@example.com")
	page.fill("input[name=password]", PASSWORD)
	page.submit()

	return page.load(path)


def test_forgot_password_emails_a_link_that_resets_the_password_once(users, mail_outbox):

	app = make_full_app()
	accounts.create_user("ada@example.com", PASSWORD)

	page = ask_for_reset(app, " ADA@example.com")
	assert "If an account exists for that email, we've emailed a link" in page.text()

	(message,) = mail_outbox
	assert message.to == ["ada@example.com"] and message.subject == "Reset your password"
	assert message.links[0].startswith("http://localhost/reset-password?token=")
	assert "60 minutes" in message.text

	reset = app.test_page(link_path(message))
	assert reset.find("button").text == "Change password"
	choose_password(reset, "new password!")
	assert "Your password has been changed." in reset.text()
	assert reset.find("a", text="Log in").attrs["href"] == "/login"

	assert can_log_in(app, "new password!")
	assert not can_log_in(app, PASSWORD)
	# The email has been proven to be the user's
	assert users.find_one()["verified"] is True

	# The link only works once
	again = app.test_page(link_path(message))
	assert "This link is invalid or has expired." in again.text()
	assert again.find("a", text="Get a new link").attrs["href"] == "/forgot-password"
	assert again.find_all("input[name=password]") == []


def test_forgot_password_says_the_same_for_unknown_emails(users, mail_outbox):

	app = make_full_app()
	accounts.create_user("ada@example.com", PASSWORD)

	known = ask_for_reset(app, "ada@example.com").text()
	unknown = ask_for_reset(app, "nobody@example.com").text()

	assert known == unknown
	assert [message.to for message in mail_outbox] == [["ada@example.com"]]


def test_reset_link_expires(users, mail_outbox, monkeypatch):

	app = make_full_app(reset_link_seconds=600)
	accounts.create_user("ada@example.com", PASSWORD)
	ask_for_reset(app)
	path = link_path(mail_outbox[0])
	assert "10 minutes" in mail_outbox[0].text

	now = time.time()
	monkeypatch.setattr(accounts, "_clock", lambda: now + 599)
	page = app.test_page(path)
	assert page.find_all("input[name=password]")

	# Expired while the form was open: refused on submit
	monkeypatch.setattr(accounts, "_clock", lambda: now + 601)
	choose_password(page, "new password!")
	assert "This link is invalid or has expired." in page.text()
	assert "This link is invalid or has expired." in app.test_page(path).text()
	assert can_log_in(app, PASSWORD)


def test_reset_link_dies_when_the_password_changes_and_cant_be_forged(users, mail_outbox):

	app = make_full_app()
	user = accounts.create_user("ada@example.com", PASSWORD)
	ask_for_reset(app)
	path = link_path(mail_outbox[0])
	token = path.split("token=")[1]

	with app.test_request_context():
		accounts.set_password(user["_id"], "changed meanwhile")
		stamp = accounts._password_stamp(accounts.users.find_one())

		# A token of another kind (verification) isn't a reset token, nor is an altered one
		other_kind = accounts._serializer(accounts.VERIFY_SALT).dumps({"user": user["_id"], "stamp": stamp})
		for bad in [other_kind, token[:-2] + "xx", token]:
			with pytest.raises(accounts.AccountError, match="invalid or has expired"):
				accounts.reset_password(bad, "attacker's choice")

	assert "This link is invalid or has expired." in app.test_page(path).text()

	# Nor is one signed with another key
	other = make_full_app()
	other.secret_key = "another secret"
	with other.test_request_context():
		forged = accounts._serializer(accounts.RESET_SALT).dumps({"user": user["_id"], "stamp": stamp})
	assert "invalid or has expired" in app.test_page(f"/reset-password?token={forged}").text()
	assert can_log_in(app, "changed meanwhile")


def test_reset_form_checks_the_new_password(users, mail_outbox):

	app = make_full_app()
	accounts.create_user("ada@example.com", PASSWORD)
	ask_for_reset(app)
	page = app.test_page(link_path(mail_outbox[0]))

	choose_password(page, "short")
	assert "Use a password of at least 8 characters" in page.text()

	choose_password(page, "new password!", "something else")
	assert "The passwords don't match" in page.text()
	assert can_log_in(app, PASSWORD)

	choose_password(page, "new password!")
	assert can_log_in(app, "new password!")


def test_reset_emails_are_rate_limited_for_every_address(users, mail_outbox):

	app = make_full_app(max_emails=2)
	accounts.create_user("ada@example.com", PASSWORD)

	for email in ["ada@example.com", "nobody@example.com"]:
		for _ in range(2):
			assert "we've emailed a link" in ask_for_reset(app, email).text()
		# Known or not, the third gets the same answer
		assert "Too many emails sent." in ask_for_reset(app, email).text()

	assert len(mail_outbox) == 2


def test_reset_emails_from_one_address_are_limited_across_emails(users, mail_outbox):

	app = make_full_app(max_emails=1)

	# One address gets four times as many
	for number in range(4):
		assert "we've emailed a link" in ask_for_reset(app, f"guess{number}@example.com").text()
	assert "Too many emails sent." in ask_for_reset(app, "another@example.com").text()


def test_links_in_emails_use_the_public_url_setting(users, mail_outbox):

	app = make_full_app(reset_url="/account/reset?step=2")
	app.settings["public_url"] = "https://example.com/"
	accounts.create_user("ada@example.com", PASSWORD)

	ask_for_reset(app)

	assert mail_outbox[0].links[0].startswith("https://example.com/account/reset?step=2&token=")


def test_links_outside_a_request_need_the_public_url_setting(users, mail_outbox):

	app = make_full_app()
	user = accounts.create_user("ada@example.com", PASSWORD)

	with app.app_context():
		with pytest.raises(accounts.AccountsConfigError, match="public_url"):
			accounts.send_reset_email(user)
		app.settings["public_url"] = "https://example.com"
		accounts.send_verification_email(user)

	assert mail_outbox[0].links[0].startswith("https://example.com/verify-email?token=")


def test_login_form_links_to_forgot_password_when_configured(users):

	assert "Forgot your password?" not in make_full_app().test_page("/").text()

	page = make_full_app(forgot_url="/forgot").test_page("/")
	assert page.find("a", text="Forgot your password?").attrs["href"] == "/forgot"


def sign_up(app, email="ada@example.com", next_url="/"):

	page = app.test_page(f"/signup?next={next_url}")
	page.fill("input[name=email]", email)
	page.fill("input[name=password]", PASSWORD)
	page.submit()

	return page


def test_sign_up_sends_no_email_unless_verify_email_is_on(users, mail_outbox):

	sign_up(make_full_app())

	assert mail_outbox == []
	assert users.find_one()["verified"] is False


def test_verify_email_after_sign_up(users, mail_outbox):

	app = make_full_app(verify_email=True)
	page = sign_up(app, next_url="/members")

	# Signed in but not verified: sent to the check-your-email page
	assert page.path == "/check-email"
	assert "We've emailed a link to ada@example.com" in page.text()
	(message,) = mail_outbox
	assert message.subject == "Verify your email"
	assert message.links[0].startswith("http://localhost/verify-email?token=")
	assert "next=%2Fmembers" in message.links[0]
	assert users.find_one()["verified"] is False

	verified = app.test_page(link_path(message))
	assert "Your email is verified." in verified.text()
	assert verified.find("a", text="Continue").attrs["href"] == "/members"

	page.load("/members")
	assert page.text("p.members") == "Welcome ada@example.com"
	with app.test_request_context():
		assert accounts.users.find_one()["verified"] is True

	# Opening the link again does no harm
	assert "Your email is verified." in app.test_page(link_path(message)).text()


def test_login_required_verified_sends_visitors_to_log_in_first(users):

	app = make_full_app()
	client = app.test_client()
	assert client.get("/members").headers["Location"] == "/login?next=%2Fmembers"

	accounts.create_user("ada@example.com", PASSWORD)
	log_in(client)
	assert client.get("/members?tab=1").headers["Location"] == "/check-email?next=%2Fmembers%3Ftab%3D1"

	app.settings["accounts"] = {"check_email_url": "/verify?step=1"}
	assert client.get("/members").headers["Location"] == "/verify?step=1&next=%2Fmembers"


def test_verification_links_expire_and_only_fit_their_email(users, mail_outbox, monkeypatch):

	app = make_full_app(verify_email=True, verify_link_seconds=60)
	sign_up(app)
	path = link_path(mail_outbox[0])

	now = time.time()
	monkeypatch.setattr(accounts, "_clock", lambda: now + 61)
	page = app.test_page(path)
	assert "This link is invalid or has expired." in page.text()
	assert page.find("a", text="Get a new link").attrs["href"].startswith("/check-email")
	monkeypatch.setattr(accounts, "_clock", time.time)

	# A link for an address the user no longer has doesn't verify them
	users.update({}, {"$set": {"email": "new@example.com"}})
	assert "invalid" in app.test_page(path).text()
	assert users.find_one()["verified"] is False


def test_check_email_page_resends_the_link_a_few_times(users, mail_outbox):

	app = make_full_app(verify_email=True, max_emails=2)
	page = sign_up(app, next_url="/members")
	assert page.path == "/check-email" and len(mail_outbox) == 1

	page.click("button", text="Send it again")
	assert "Sent. Check your inbox." in page.text()
	page.click("button", text="Send it again")
	page.click("button", text="Send it again")
	assert "Too many emails sent." in page.text()
	assert len(mail_outbox) == 3

	# Any of them works
	app.test_page(link_path(mail_outbox[1]))
	page.load("/members")
	assert page.path == "/members"


def test_oauth_users_with_a_verified_email_are_verified(users, monkeypatch):

	monkeypatch.setattr(accounts, "_fetch_json", github_user())
	client = make_app(**GITHUB).test_client()

	_, query = start_oauth(client)
	finish_oauth(client, query["state"])

	assert users.find_one()["verified"] is True


def change_password(page, current, new, confirm=None):

	page.fill("input[name=current]", current)
	page.fill("input[name=password]", new)
	page.fill("input[name=confirm]", new if confirm is None else confirm)
	page.submit()

	return page


def test_change_password(users, mail_outbox):

	app = make_full_app()
	accounts.create_user("ada@example.com", PASSWORD)
	ask_for_reset(app)
	reset_path = link_path(mail_outbox[0])
	page = log_in_page(app, "/account")

	change_password(page, "wrong password", "new password!")
	assert "Wrong password" in page.text()

	change_password(page, PASSWORD, "new password!", "typo")
	assert "The passwords don't match" in page.text()
	assert "has been changed" not in page.text()

	change_password(page, PASSWORD, "new password!")
	assert "Your password has been changed." in page.text()
	assert page.value("input[name=current]") == ""

	assert can_log_in(app, "new password!")
	assert not can_log_in(app, PASSWORD)
	# A reset link sent before doesn't work any more
	assert "invalid or has expired" in app.test_page(reset_path).text()


def test_wrong_current_passwords_count_as_failed_logins(users):

	app = make_full_app(max_attempts=2)
	accounts.create_user("ada@example.com", PASSWORD)
	page = log_in_page(app, "/account")

	for _ in range(2):
		change_password(page, "wrong password", "new password!")
	change_password(page, PASSWORD, "new password!")

	assert "Too many failed attempts." in page.text()
	assert not can_log_in(app, PASSWORD)
	accounts._failures.clear()
	assert can_log_in(app, PASSWORD)


def test_change_password_form_asks_visitors_to_log_in(users):

	app = make_full_app()

	@app.route("/change")
	def change():
		return Document() [accounts.ChangePasswordForm()]

	assert "Log in to change your password." in app.test_page("/change").text()
