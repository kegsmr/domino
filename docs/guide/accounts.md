# Accounts

Sign-up, login, password reset and email verification, with GitHub and Google.

`domino.accounts` adds sign-up, login and logout. Users are documents in the `users` collection (MongoDB):

```python
from domino import accounts

@app.route("/")
def index():
    return Document() [accounts.UserMenu()]        # "Signed in as …" + Log out, or Log in / Sign up links

@app.route("/login")
def login():
    return Document() [accounts.LoginForm()]       # also SignupForm(), LogoutButton(), OAuthButton("github"),
                                                   # ForgotPasswordForm(), ChangePasswordForm(), ... (below)

@app.route("/private")
@accounts.login_required                           # under @app.route, or on a page's page()
def private():
    user = accounts.current_user()
    return Document() [t.p() [f"Hello {user['email']}"]]
```

- `accounts.current_user()` is the signed-in user's document (without its password hash), or None; `accounts.user_id()` is just the id. Both are reactive: a component that reads them in `render()` re-renders when the user logs in or out on that page.
- `accounts.create_user(email, password, name=None)`, `accounts.login(email, password)` and `accounts.logout()` can be called from your own event handlers. Bad input raises `accounts.AccountError`, whose message is meant for the user (a wrong email and a wrong password both give "Wrong email or password"). Passwords need at least 8 characters and are hashed with werkzeug's `generate_password_hash`; emails are stored lowercased and must be unique (a unique index is created in MongoDB).
- The forms show errors inline, keep the typed email, and after logging in go to `?next=` if the page has one (only paths on this site are followed). `login_required` sends visitors who aren't signed in to the `accounts.login_url` setting (default `/login`) with `?next=` set to the page they asked for.
- After 5 failed logins for an email within a minute, it's locked until that minute has passed; one IP address gets 20. Change these with the `accounts.max_attempts` and `accounts.lockout_seconds` settings. The counts are kept in the server process's memory, so each process (and a restart) counts on its own. Behind a proxy, every client shares the proxy's address unless you set up Werkzeug's `ProxyFix`.
- `domino.redirect(url)` in any event handler sends the browser to `url` when the response arrives. It only accepts paths on this site (`/notes`, not `//evil.com` or `https://...`); outside event handlers it's Flask's `redirect()`.
- The forms are [`domino.forms`](forms.md#forms) forms (`LoginForm`, `SignupForm` and the ones below), so they're laid out and styled like any other, and can be subclassed to change labels, messages or `submit_text`.

## Password reset, email verification and changing the password

These send email, so set up [Email](email.md#email) first (in debug mode emails are printed in the terminal, links included). Put each component on a page of its own, like the login page:

```python
# pages/forgot-password.py
def page():
    return accounts.ForgotPasswordForm()          # email -> "If an account exists for that email, we've emailed a link ..."

# pages/reset-password.py                        # the emailed link: /reset-password?token=...
def page():
    return accounts.ResetPasswordForm()           # new password + confirmation

# pages/verify-email.py                          # the link emailed after signing up
def page():
    return accounts.VerifyEmail()

# pages/check-email.py                           # "check your email", with a button to send the link again
def page():
    return accounts.CheckEmail()

# pages/members.py
@accounts.login_required(verified=True)          # unverified users go to /check-email?next=...
def page():
    ...

# pages/settings.py
@accounts.login_required
def page():
    return accounts.ChangePasswordForm()          # current password + new password + confirmation
```

- **Forgot your password?** `ForgotPasswordForm` gives the same answer whether or not an account has that email, so it can't be used to find out who has one (emails go out in the background, so it doesn't take longer either). The email links to the `accounts.reset_url` page (default `/reset-password`) with a token that expires after `accounts.reset_link_seconds` (default 3600) and works once: it's bound to the user's current password hash, so it stops working as soon as the password is reset or changed. Resetting also marks the email verified (the link proved it's theirs) and ends a login lockout. With the `accounts.forgot_url` setting (e.g. `/forgot-password`), `LoginForm` shows a "Forgot your password?" link to it.
- **Email verification.** With `{"accounts": {"verify_email": true}}` (off by default), `SignupForm` emails new users a link to the `accounts.verify_url` page (default `/verify-email`), valid for `accounts.verify_link_seconds` (default 3 days). `current_user()["verified"]` says whether they've opened it; users who signed in with GitHub or Google with a verified email are verified already. `@accounts.login_required(verified=True)` sends unverified users to the `accounts.check_email_url` page (default `/check-email`), whose button sends the link again. Your own code can call `accounts.send_verification_email(user)`, `accounts.send_reset_email(user)`, `accounts.verify_email(token)`, `accounts.reset_password(token, password)` and `accounts.set_password(user_id, password)`.
- **Changing the password.** `ChangePasswordForm` asks for the current password; wrong guesses count as failed logins for that email, so they're locked out the same way. Other browsers signed in to the account stay signed in: sessions live in cookies, so there's no server-side list of them to end ("log out other sessions" isn't possible). Reset links sent before stop working.
- **Rate limits.** Reset emails are limited per address (whether or not it has an account) and verification emails per user: `accounts.max_emails` (default 3) in `accounts.email_window_seconds` (default 900), and four times as many per IP address. Like the login lockout, the counts are kept in each server process's memory.
- **Links** in emails are built on the `public_url` setting (`{"public_url": "https://example.com"}`), or else on the address the request came to. It's required for emails sent over SMTP outside debug mode (sending raises `AccountsConfigError` without it): otherwise a request with a forged `Host` header could get a reset link to another site emailed to a user. OAuth callback URLs use it too when it's set. A reset link also stops working once the account's email changes. Tokens are signed with the `secret_key` and a salt per purpose, so a verification token can't be used as a reset token, and changing the secret key invalidates them all.

**Sessions.** The signed-in user's id is kept in Flask's signed session cookie, which needs the `secret_key` setting: put a long random string in `settings.local.json` or `DOMINO_SECRET_KEY`. In debug mode an app without one gets a random key per process, with a warning, so logins don't survive a restart; outside debug mode accounts refuse to work without it. Domino pages outlive their request (events and pushes from other users' changes run later), so each page remembers who was signed in when it was loaded, and login and logout update the page as well as the cookie. Other open tabs of the same browser notice on their next page load, not live. Logging in starts a fresh session (nothing from the old cookie is kept) and lasts 31 days (Flask's `PERMANENT_SESSION_LIFETIME`); logging out clears the cookie in that browser. Since the session lives in the cookie, there's no server-side list of sessions to revoke.

**Cookies.** Domino apps send the session cookie with `HttpOnly` (Flask's default), `SameSite=Lax`, and, outside debug mode, `Secure`, so in production it's only sent over HTTPS. For an HTTP-only deployment set `{"domino": {"secure_cookies": false}}`. Responses also carry `X-Frame-Options: SAMEORIGIN` (so another site can't frame your pages and trick visitors into clicking their buttons; `{"domino": {"frame_options": false}}` turns it off), `X-Content-Type-Options: nosniff` and `Referrer-Policy: strict-origin-when-cross-origin`, unless a response sets its own. See SECURITY.md for the rest of the security model.

**Events and CSRF.** The event endpoint accepts only `application/json` requests (anything else gets 415). A form on another site can't send JSON, and another site's script can't send it without a CORS preflight, which Domino never allows, so a malicious page can't fire events with the user's cookie. Events also need the page's random id, which only the page itself has.

**Keep the users collection on the server.** Domino has no client-side database: the browser only sees what components render. Render fields you choose (`user["name"]`), never whole user documents, and don't build components that list `accounts.users` for everyone. `current_user()` leaves out the password hash, but `accounts.users.find()` doesn't.

## GitHub and Google

Add a provider's OAuth app credentials to the settings, for example in `settings.local.json`:

```json
{"accounts": {"github": {"client_id": "...", "client_secret": "..."}, "google": {"client_id": "...", "client_secret": "..."}}}
```

The callback URL to register with the provider is `https://<your site>/_domino/accounts/github/callback` (or `google`). `LoginForm` and `SignupForm` then show a "Continue with GitHub" link, and `OAuthButton("github")` adds one anywhere; providers that aren't configured render nothing. Signing in uses the authorization-code flow with a random `state` kept in the session, so a callback this browser didn't start is refused. The user is found by their provider account id, or else linked to an existing user with the same email if the provider says it's verified, or else created; an unverified email never links to an existing account. Provider details are kept in `user["services"]["github"]`; access tokens aren't stored.

See `examples/accounts/`.
