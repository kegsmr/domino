# Domino

An experimental Python web framework built on Flask. It currently resembles a glorified HTML/CSS generator, but more features are planned.

**This project is a work-in-progress! Not all features are functional yet.**

## Install

The distribution is named `domino-web`; the import name is `domino`.

```
pip install -e .
```

## Run an example

```
python examples/counter/app.py
```

Then open http://127.0.0.1:5000. Each example is a folder with a small `app.py` and its pages in `pages/`; see [examples/README.md](examples/README.md).

## Pages

Each Python file in the app's `pages/` folder is a page, and its path is the URL:

```
myapp/
  app.py                 app = Domino(__name__)
  pages/
    index.py             /
    about.py             /about
    users/
      index.py           /users
      [id].py            /users/<id>
      [id]/posts.py      /users/<id>/posts
    docs/[...path].py    /docs/<path:path>, the rest of the URL
    layout.py            wraps every page in its folder and below
    404.py               the page for URLs no page serves
    _helpers.py          not a page: names starting with _ are private
  components/            components the pages import
  data.py                Collections the pages import
  settings.json
```

A page file defines `page()`, returning anything a route can: a component, a `Document`, a string or a Flask response. The parts of the URL in brackets arrive as keyword arguments. `[int:id].py` uses Flask's `int` converter (`float`, `uuid` and `path` work too), and `[...path].py` matches the rest of the URL, slashes included (at least one segment: `/docs` itself needs `docs/index.py`).

```python
# pages/users/[int:id].py  ->  /users/42
import domino.tags as t


def page(id):

	return t.h1() [
		f"User {id}"
	]
```

A page can also be a component class named `Page`. Each visit gets a new one, and the URL's parameters are passed to its `init(self, ...)`:

```python
# pages/counter.py  ->  /counter
from domino import State
import domino.tags as t


class Page(t.div):

	count = State(0)


	def render(self):

		return [
			t.button(on_click=self.increment) [
				f"Clicked {self.count} times"
			]
		]


	def increment(self):

		self.count += 1
```

`layout.py` defines `layout(content)` and returns the page wrapped in whatever every page shares, usually a `Document` with the navigation. Layouts nest: the `pages/` folder's own layout is the outermost, then each subfolder's, down to the page's own folder. A layout that names URL parameters (`layout(content, id)`) receives them.

```python
# pages/layout.py
import domino.tags as t
from domino.components import Document


def layout(content):

	return Document(title="My site") [
		t.nav() [
			t.a(href="/") ["Home"],
			t.a(href="/about") ["About"]
		],
		content
	]
```

- A page that returns a whole document (a `Document`, or any `t.html`) or a Flask response is used as it is, without layouts.
- A component that no layout puts in a document is put in a plain `Document()`, which loads Domino's script, so its events work.
- `404.py`'s `page()` is shown, inside the layouts and with status 404, for URLs no page or route serves, and for `abort(404)`.
- The app's folder is on the import path, whatever the current folder is, so pages can `from components.chat import Chat` and `from data import messages`. Pages are imported while the app is created, so they can't import `app.py`; read settings with `flask.current_app.settings`.

Pages are on when the app's folder (the folder of the module passed to `Domino(__name__)`) has a `pages/` folder. `Domino(__name__, pages="views")` uses another folder and `pages=False` turns them off. `@app.route` keeps working alongside pages; a route for a URL a page already serves is an error, naming both, when the app starts. Pages are found once, when the app is created, and each file is imported once; while debugging, the reloader restarts the server when one changes. Pages render exactly like `@app.route` views, with events, reactive data and server push.

## Command line

Installing the package adds a `domino` command, modeled on `meteor`:

```
domino create myapp
cd myapp
domino run
```

`domino create <name>` makes a folder with a small reactive app: a tiny `app.py`, `pages/index.py` and `pages/layout.py`, a component in `components/`, a `Collection` in `data.py`, a `settings.json` with a `public` block, and a `.gitignore`. It won't write into a folder that isn't empty.

`domino run [folder or app.py] [--port 5000] [--host 127.0.0.1] [--no-mongo] [--mongo-version 7.0]` runs the app (default: the current folder) in debug mode with the reloader, so it restarts when you save a file. For a folder it runs its `app.py`; a folder with only `pages/` (and maybe `settings.json`) needs no `app.py` at all, as `domino run` makes the app itself. `domino --version` prints the version.

### Development MongoDB

Like `meteor run`, running an app in debug mode starts a local MongoDB for it, unless its settings already have `mongo.url`. This happens with `domino run`, and also with `app.run(debug=True)` (or `FLASK_DEBUG=1`, or `app.debug = True`). Importing the app, tests, `flask run` and production servers never start one.

- The first time, the newest MongoDB 7.0 release built for your OS and CPU is downloaded from mongodb.org (about 100MB), checked against its published SHA-256, and only `mongod` is kept, in `~/.domino/mongodb/<version>/`. Set `DOMINO_HOME` to keep it somewhere else. Later runs use the cached binary and work offline. `--mongo-version` (or the setting `mongo.version`) picks another release series, such as `8.0`.
- `mongod` listens on 127.0.0.1, on the app's port + 1 (5001 for 5000), or on any free port if that one is busy. Its data goes in `.domino/db` in the app's folder and its log in `.domino/mongod.log`. Add `.domino/` to your app's `.gitignore` (`domino create` does).
- It runs as a single-node replica set (`rs0`), which change streams need.
- The URL, `mongodb://127.0.0.1:5001/<app folder name>?replicaSet=rs0&directConnection=true`, is put in `app.settings.mongo.url` and the `DOMINO_MONGO__URL` environment variable before the server starts, so the reloader's process uses the same database.
- `mongod` stops when the app does (Ctrl+C, or the process being terminated). On Linux it also stops if the app is killed. A second `domino run` of the same app reuses the running `mongod`, and a lock left by one that crashed is cleared.
- To turn it off, pass `--no-mongo`, set `DOMINO_NO_MONGO=1`, or set `{"mongo": {"auto": false}}` in `settings.json`.

In production, point the app at your database with the `mongo.url` setting, usually from the environment: `DOMINO_MONGO__URL=mongodb://...`. Without debug mode nothing is downloaded or started.

The development MongoDB needs `pymongo`, which is installed with Domino.

## Attributes

Keyword arguments become HTML attributes; underscores turn into hyphens (`aria_label` → `aria-label`, `data_user_id` → `data-user-id`). A trailing underscore avoids Python keywords (`for_` → `for`). `class_` (a string or list) adds CSS classes after the component's own, and `style` accepts a dict:

```python
t.button(class_="btn btn-primary", aria_pressed="false", style={"font_weight": "bold"})
```

## Styles

A component declares its styles on the class, with `css`. They are scoped to its class name and written into the page's `<head>` once, however many times the component is shown:

```python
class Card(t.div):

	css = {
		"padding": "1rem",                              # .Card
		"background": "var(--surface)",
		"h3": {"margin": 0},                            # .Card h3
		":hover": {"box_shadow": "0 2px 8px #0002"},    # .Card:hover
		"& + &": {"margin_top": "1rem"},                # .Card + .Card
		"@media (max-width: 600px)": {"padding": ".5rem"},
	}
```

- Property names are written with underscores (`font_size`); `__accent` (or `"--accent"`) is the CSS variable `--accent`. Values are written as given (no units are added), and `None` leaves a property out.
- A nested key is a selector. Keys starting with `:` or `[` (`":focus"`, `"::after"`, `"[open]"`) attach to the enclosing selector, other keys (`"h3"`, `"> li"`, `"input, textarea"`) select descendants, and `&` stands for the enclosing selector anywhere (`"&.active"`, `"& + &"`). `""` is the component itself.
- `@media`, `@supports`, `@container` and `@layer` blocks hold the same kind of rules; other at-rules, such as `@keyframes` and `@font-face`, are written as they are, unscoped.
- `css` can also be plain CSS, scoped the same way: `css = "& { padding: 1rem } h3 { margin: 0 }"`.
- Subclasses keep their base class's styles (the element has both classes) and add their own, which come later and so win.
- When a component first appears in an event response or a push, its CSS comes with it and is added to the page once.

A page's own rules go on the `Document`, and can be added at any point, including from a component's `render()`, since the page's CSS is computed when it has finished rendering:

```python
page.style("body", font_family="system-ui", margin="2rem auto")
page.style("a", {":hover": {"color": "red"}, "@media print": {"color": "black"}})  # nested, as in css
page.theme(surface="#fff", text="#111", dark={"surface": "#111", "text": "#eee"})  # --surface, --text
```

`theme()` sets CSS variables on `:root`, with the `dark` values for visitors whose system prefers a dark color scheme. Component CSS comes before the page's in the `<head>`, so where both match equally the page wins.

Styles shared by every page can go in a stylesheet the browser caches: `stylesheet = app.style("/style.css")` serves it, `stylesheet.style(...)` adds rules to it (the same as `page.style`), and `stylesheet.link(head)` links it from a page. For a single element, use the `style` attribute (a dict, see Attributes). `stylesheet.style(element, ...)` still works too, but writes a `<style>` block for each element it's used on; for a component shown many times, `css` is much smaller.

CSS can't close the `<style>` element it's written in, whatever the values hold. See `examples/styles/`.

## Components

A component is a Python class: subclass a tag, keep state in `State` class attributes, and return its children from `render()`. Changing state re-renders the component, and only what changed is updated in the browser:

```python
from domino import Domino, State
import domino.tags as t


class Counter(t.div):

	count = State(0)  # per component, like React's useState


	def render(self):

		return [
			t.p() [f"Count: {self.count}"],
			t.button(on_click=self.increment) ["+"],
		]


	def increment(self):

		self.count += 1
```

- `on_<event>=handler` (`on_click`, `on_submit`, `on_input`, `on_change`, ...) runs `handler` on the server. Add `debounce=ms` to wait until the user pauses.
- A handler that returns nothing re-renders whatever its changes affected (or the component it belongs to); returning a component re-renders that one.
- `State` as a class attribute is per component instance; a `State` at module level is shared by everyone. Lists and dicts: assign a new value (`self.items = self.items + [x]`) or set them again after changing them in place.
- `init(self)` runs once when the component is created, for setup that isn't state.
- The older style, `self([...])` with `element.bind("click", callback)` and `return self`, still works.

## Events

`element.bind("click", callback)` (or `on_click=callback`) runs `callback` on the server. A callback that takes an argument receives an `Event`:

- `event.type`: the DOM event name (`"click"`, `"submit"`, `"change"`, ...)
- `event.value`: the element's value (`True`/`False` for checkboxes)
- `event.form`: the surrounding `<form>`'s fields as a dict (repeated names become lists)

Submit events don't reload the page. See `examples/todo/`.

`bind(event, callback, debounce=ms)` waits until the user pauses before sending, which suits `"input"` events (see `examples/search/`). An element can have several events.

Updates are patched into the page in place rather than replacing the component's HTML, so focus, the caret and anything the user is typing survive a re-render. Form fields keep what the user entered unless the server changes their value, or they belong to the element whose event was just handled (a submitted form is reset to what the server renders).

### Loading and errors

While an event's request is in flight, the element that fired it gets `aria-busy="true"` and `data-loading` (for a submit, so do the form's submit buttons), and `<html>` gets `data-domino-loading`. Buttons, selects and other controls are also disabled until the response is applied, unless they were disabled already; text fields that fire debounced `input` events are not, so typing continues. Domino adds no styles for this, so add your own:

```python
page.style("button[data-loading]", opacity="0.6", cursor="progress")
page.style("html[data-domino-loading]", cursor="progress")
```

If a callback raises, the server logs the exception and answers with status 500. In production the response only says `"Internal Server Error"`; with `app.debug` on it includes the exception and its traceback, and the browser shows them in an overlay. Either way the browser dispatches a cancelable `domino:error` event on the element that fired, which bubbles to the document, with `detail` holding `error`, `traceback` (debug only) and `eventId`. Cancel it to handle errors yourself:

```js
document.addEventListener('domino:error', (e) => {
    e.preventDefault();  // no overlay or console.error
    showToast('Something went wrong');
});
```

See `examples/loading/`.

### Server push

`component.refresh()` re-renders a component and sends it to every open page showing it, without waiting for a browser event. It can be called from anywhere, including a background thread. Mark components that will be refreshed with the class attribute `live = True`: pages showing one receive updates over Server-Sent Events from `/_domino/stream`, which keeps one connection (and, on a threaded server, one thread) open per tab, so other pages don't open a stream at all. A component shown on several pages is rendered once per refresh. See `examples/clock/`.

### Reactive data

Like Meteor, Domino components re-render themselves when the data they show changes. Reading a `State` or querying a `Collection` inside `render()` subscribes the component; changing it re-renders every subscribed component on every open page and pushes the result (no `live = True` needed):

```python
from domino import Collection, State

messages = Collection("messages")   # shared by everyone
online = State(0)

class Chat(t.ul):

	def render(self):
		return [t.li() [m["text"]] for m in messages.find(sort=[("sent", -1)], limit=50)]

	def send(self, event):
		messages.insert({"text": event.form["text"], "sent": time.time()})  # every Chat updates
```

- `State(value)`: `.value` reads (and subscribes), `.value = x` changes it.
- `Collection(name)`: `insert(doc)` (returns the `_id`), `find(query, sort=..., limit=...)` (a cursor you iterate or `.fetch()`), `find_one`, `count`, `update(query, {"$set": ...}, multi=False)` and `remove(query)`, with MongoDB-style queries (`$gt`, `$in`, `$or`, dotted paths, ...). Documents come back as copies.
- Changes made while handling an event re-render each subscriber once, in the background, so the user who made the change gets their response straight away. Use `with batch():` to group changes made elsewhere, and `domino.wait()` in tests to let background updates finish.

See `examples/chat/`.

### MongoDB

Like Meteor, named collections live in MongoDB: `Collection("messages")` is the `messages` collection of the app's database, and `Collection()` without a name is an in-memory collection for this process only. Queries and updates use MongoDB's own syntax (all of it, not just the subset the in-memory collection supports). Documents get a string `_id` unless they have one.

The database comes from the `mongo.url` setting (e.g. `DOMINO_MONGO__URL=mongodb://db:27017/myapp?replicaSet=rs0`), with the database name taken from the URL (default `domino`); `MONGO_URL` works too, and `domino.mongo.connect(url)` sets it in code. When MongoDB runs as a replica set, a change stream per collection re-renders subscribers when *any* process changes the collection — another server process, a script, or `mongosh` — so it also works with several server processes. Without a replica set only this process's own writes update pages live.

## Accounts

`domino.accounts` adds sign-up, login and logout, like Meteor's accounts packages. Users are documents in the `users` collection (MongoDB):

```python
from domino import accounts

@app.route("/")
def index():
	return Document() [accounts.UserMenu()]        # "Signed in as …" + Log out, or Log in / Sign up links

@app.route("/login")
def login():
	return Document() [accounts.LoginForm()]       # also SignupForm(), LogoutButton(), OAuthButton("github")

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

**Sessions.** The signed-in user's id is kept in Flask's signed session cookie, which needs the `secret_key` setting: put a long random string in `settings.local.json` or `DOMINO_SECRET_KEY`. In debug mode an app without one gets a random key per process, with a warning, so logins don't survive a restart; outside debug mode accounts refuse to work without it. Domino pages outlive their request (events and pushes from other users' changes run later), so each page remembers who was signed in when it was loaded, and login and logout update the page as well as the cookie. Other open tabs of the same browser notice on their next page load, not live. Logging in starts a fresh session (nothing from the old cookie is kept) and lasts 31 days (Flask's `PERMANENT_SESSION_LIFETIME`); logging out clears the cookie in that browser. Since the session lives in the cookie, there's no server-side list of sessions to revoke.

**Cookies.** Domino apps send the session cookie with `HttpOnly` (Flask's default), `SameSite=Lax`, and, outside debug mode, `Secure`, so in production it's only sent over HTTPS. For an HTTP-only deployment set `{"domino": {"secure_cookies": false}}`.

**Events and CSRF.** The event endpoint accepts only `application/json` requests (anything else gets 415). A form on another site can't send JSON, and another site's script can't send it without a CORS preflight, which Domino never allows, so a malicious page can't fire events with the user's cookie. Events also need the page's random id, which only the page itself has.

**Keep the users collection on the server.** Domino has no client-side database: the browser only sees what components render. Render fields you choose (`user["name"]`), never whole user documents, and don't build components that list `accounts.users` for everyone. `current_user()` leaves out the password hash, but `accounts.users.find()` doesn't.

### GitHub and Google

Add a provider's OAuth app credentials to the settings, for example in `settings.local.json`:

```json
{"accounts": {"github": {"client_id": "...", "client_secret": "..."}, "google": {"client_id": "...", "client_secret": "..."}}}
```

The callback URL to register with the provider is `https://<your site>/_domino/accounts/github/callback` (or `google`). `LoginForm` and `SignupForm` then show a "Continue with GitHub" link, and `OAuthButton("github")` adds one anywhere; providers that aren't configured render nothing. Signing in uses the authorization-code flow with a random `state` kept in the session, so a callback this browser didn't start is refused. The user is found by their provider account id, or else linked to an existing user with the same email if the provider says it's verified, or else created; an unverified email never links to an existing account. Provider details are kept in `user["services"]["github"]`; access tokens aren't stored.

See `examples/accounts.py`.

## Settings

`app.settings` holds the app's settings, merged from (later wins):

1. `settings.json` in the app's folder (the folder of the module passed to `Domino(__name__)`), committed with the app
2. `settings.local.json` next to it, for local overrides; it's in `.gitignore`
3. `DOMINO_*` environment variables

Every source is optional. Nested objects merge key by key, so a local file can override one nested value without repeating the rest; lists and other values replace. `Domino(__name__, settings="config/app.json")` reads a different file (and `config/app.local.json`), and the `DOMINO_SETTINGS` environment variable points at another settings file, like `meteor --settings`.

An environment variable `DOMINO_<KEY>` sets the top-level key `<key>` (lowercased), and a double underscore nests: `DOMINO_MONGO__URL=mongodb://db` sets `settings["mongo"]["url"]`. Values are parsed as JSON when they parse (`8080`, `true`, `null`, `[1, 2]`, `{"a": 1}`) and kept as strings otherwise.

Settings work as a dict or with attributes: `app.settings.mongo.url`, `app.settings["mongo"]["url"]`, `app.settings.get("mongo")`.

```json
{
    "secret_key": "...",
    "domino": {"page_ttl": 600, "max_pages": 500, "keepalive": 15},
    "public": {"greeting": "Hello"}
}
```

- `domino` sets Domino's Flask config: `page_ttl` becomes `app.config["DOMINO_PAGE_TTL"]`, and so on. Changes to `app.config` made in code afterwards still win. From the environment, these are `DOMINO_DOMINO__PAGE_TTL=600` and so on.
- `secret_key` sets `app.secret_key`.
- `public` is sent to the browser, where it's available as `Domino.settings` (like `Meteor.settings.public`). `Document` adds it to the page head; pages built without `Document` can add `PublicSettings()` from `domino.components` to theirs. Nothing outside `public` is sent.

See `examples/settings/`.

### Instant updates

Handlers that only change their component's own `State` with plain expressions — `self.count += 1`, `self.open = not self.open`, `if len(self.items) < 3: ...` — feel instant even on a slow connection, with nothing to configure. When the server renders such a component it also renders how it will look after each of those handlers and ships that inside the component (inert JSON); the browser shows it the moment the user clicks, and the server's real answer then confirms it or puts it right. Domino decides which handlers qualify by reading their code: anything that calls functions (like `messages.insert(...)`), uses the event's value, or touches anything but the component's `State` is never run ahead of time. While a prediction is showing, the component has a `data-predicted` attribute. Set `optimistic = False` on a component class to turn it off (each prediction costs a render).

### Simulating a slow connection

Locally every click feels instant. To feel the app the way users on a slow connection will, run `Domino.enableLatencySim(300)` in the browser console: each round trip to the server then takes 300 ms (pushes are delayed too), for that tab, until `Domino.disableLatencySim()`. Or set it for the whole app while debugging with `{"domino": {"latency": 300}}` in `settings.json`; it's ignored when the app isn't in debug mode.

## Testing your app

Tests live next to the page they test: `pages/about_test.py` tests `pages/about.py`. Its `page` fixture is that page, open in a simulated browser, so a test file needs no imports and no setup. Run them with plain `pytest` (Domino installs the pytest plugin):

```python
# pages/index_test.py
def test_increment(page):
	page.click("button", text="Increment")
	assert page.text("p") == "Current Count: 1"

def test_add_a_task(page):
	page.fill("input[name=text]", "Buy milk")
	page.click("button", text="Add")      # a submit button submits its form
	assert page.text("ul") == "Buy milk"
	assert page.value("input[name=text]") == ""
```

There's no real browser and no server running, but clicks, typing and form submits go through the same code as in a browser: handlers, `State`, collections and pushed updates all run for real, in about a millisecond each. For a page with URL parameters, use `open_page`: in `pages/users/[id]_test.py`, `open_page(id=3)` opens `/users/3`. `open_page("/about")` opens any path of the app, and each call is a new browser tab. Files ending in `_test.py` are never served as pages. (pytest won't take a path with `[...]` on the command line; run the folder, or pick tests with `-k`.)

Find elements with simple CSS selectors (`tag`, `.class`, `#id`, `[attr=value]`, and descendants like `form input`), optionally narrowed with `text=`. Pages can be driven with `click`, `fill` (set a value without firing events), `type` (fires `input`), `select`, `check`, and `submit`. Inspect them with `text`, `value`, `find`/`find_all`, `html`, `status` and `path`. `sync()` applies changes other pages pushed to this one, `run_timers()` fires pending `after()` timers right away, and `load(path)` navigates (redirects are followed and cookies kept, like a browser, so a login carries over). A failing handler, or a selector that matches nothing, fails the test with the traceback and the page's text.

Outside `pages/`, `app.test_page(path)` gives the same simulated browser for any app. See the examples' `pages/*_test.py`, e.g. [examples/counter/pages/index_test.py](examples/counter/pages/index_test.py).

## Deployment

Components and their event handlers live in the memory of the server process that rendered the page. Each page load gets its own state, which expires after `DOMINO_PAGE_TTL` seconds of inactivity (default 1800). At most `DOMINO_MAX_PAGES` pages are kept (default 1000); when a page has expired, the browser reloads it.

Because of that, run a single process, or use sticky sessions so a browser keeps talking to the same worker. To change how pages are kept, subclass `domino.PageStore` (or `MemoryPageStore`) and pass `Domino(__name__, page_store=...)`. A store shared between processes would need to serialize components and their callbacks.

## Tests

```
pip install -e .[test]
python -m pytest
```

## Releasing

Bump `version` in `setup.py`, then publish a GitHub Release (e.g. tag `v0.1.0`). The `Publish to PyPI` workflow builds the package and uploads it to PyPI as `domino-web`.
