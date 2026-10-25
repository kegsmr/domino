# Changelog

## 0.3.0

### Development
- Hot reload that keeps state, like React Fast Refresh: save a component, page or template and open pages update in place in about 100 ms, keeping State, typed text and focus. Changes that can't be swapped safely (app.py, settings) restart the server.
- Developer tools (debug mode only): an error page for pages that fail to render (source around each frame, the component stack, hints); a richer event error overlay; a component inspector (Alt+Shift+D or `Domino.inspect()`) with live State, events and why a handler isn't instant; an event log with timings. Production pages are unchanged, byte for byte.
- `python -m domino` runs the `domino` command (handy on Windows). CI also runs on Windows.
- Windows fixes: `[id=int].py` page files (colons can't be in Windows file names), hot reload restarts after `app.py` changes, client components on another drive, and paths in error pages.
- Text typed into a form while its submit is on its way is no longer cleared when the answer arrives (the next chat message, say).
- Editors know the type of `State`: with `count = State(0)`, `self.count` is an `int`, so Pylance accepts `self.count += 1` and autocompletes its methods.
- `Collection.raw_collection()` and `raw_database()`, like Meteor's: the pymongo collection and database behind a named collection, for indexes, aggregation and the like.
- The license is now MIT (it was MIT-0): copies must keep the copyright notice.

### Deploying
- `domino build` writes a Dockerfile (non-root, health check, `domino serve`), `.dockerignore` and `requirements.txt`.
- `domino deploy fly|render|docker`: fly.toml and secrets through flyctl, render.yaml, or a docker-compose.yml with MongoDB as a replica set.
- `/_domino/health`, and `domino serve` reads `WEB_CONCURRENCY`.

### Accounts and email
- `domino.mail`: SMTP, a console backend while debugging, and an outbox under pytest (`mail_outbox` fixture).
- Password reset, email verification (`login_required(verified=True)`) and changing the password. The login and sign-up forms are built on `domino.forms`.

### Styles
- Tailwind CSS with zero setup: `{"tailwind": true}` (or a `tailwind.css` in the app's folder) and classes work anywhere. Tailwind's standalone CLI is downloaded once into `~/.domino/tailwind/`; `domino run` rebuilds as files change and open pages swap in the new CSS; `domino serve` builds it minified; `domino tailwind build` for Dockerfiles; `domino create --tailwind`.

### Templates
- Domino templates: markup in `.html` files, logic in Python. A capitalized tag at the top level of a file defines that component (`<TodoList as="aside">...</TodoList>`, found anywhere in the app by class name); anywhere else it uses one (`<Card heading="x">children</Card>`, with `<slot />`). Lists and conditions are blocks in Python's words, closed like HTML (`{{ for task in tasks }}`...`{{ else }}`...`{{ /for }}`, `{{ if x }}`...`{{ elif y }}`...`{{ /if }}`), which wrap whole elements; `{{ value }}`, `:attr="helper(item)"` and `on-click="remove(item)"` read only from Python. Compiled once, escaped, whitespace kept as written, instant updates included. `.html` pages in `pages/`; layouts as components pages wrap themselves in (`<Layout title="About">...</Layout>`, defined in `layouts/layout.html` as a whole `<html>` document with `<slot />` where the page goes, no Python class needed); components that are only markup; and Meteor-style `index.html` documents. Jinja stays available. `domino create` and `examples/templating` use them.
- Components take data and handlers from their parent: keyword arguments set what the class declares (`State`, properties, class attributes, `on_add = None` callbacks).

### Speed
- Over the WebSocket, updates are sent as line-diff patches against what the tab already has: a chat message to a 200-message list goes from 28 KB to 198 bytes. Large predicted states are patched too.
- Hidden tabs pause: the server skips their updates until they're shown again.
- `{"domino": {"ws_compression": false}}` saves ~43 KB per idle tab.

### Documentation
- A documentation site built with Domino (`docs/`, `python docs/app.py`): a tutorial with live demos, and guide pages made from the README.

### Experimental
- Client components: `client = True` runs a component in the browser on MicroPython (or Pyodide), server-rendered first, working offline once loaded. See `docs/research/client-python.md`.

### Security
Fixes from a security review. Apps that deploy behind a proxy, use accounts or run in public should upgrade.
- **MongoDB operator injection:** `event.form` values are now always strings (or lists of strings). A client could send `{"$ne": null}` and make `find_one({"email": event.form["email"]})` match any document.
- **Password reset poisoning:** emails sent over SMTP outside debug mode need the `public_url` setting. Links used to be built from the request's Host header, which an attacker could forge. Reset tokens are also bound to the account's email, and email addresses can't hold characters that add recipients.
- **Behind Fly's or Render's proxy,** every visitor had the proxy's address, so one person's wrong passwords locked everyone out. `fly.toml` and `render.yaml` now trust the platform's proxy (`FORWARDED_ALLOW_IPS`), and the router can't be tricked past that check. `fly.toml` sets `DOMINO_PUBLIC_URL`. `domino serve` warns when the app is in debug mode.
- **A slow email check (ReDoS):** one sign-up with a crafted address could keep a server thread busy for hours. The check now runs in linear time.
- **HTML injection** through attribute names and `<script>` text is no longer possible.
- **A leaked page id** (it appears in `/_domino/ws` URLs, which access logs keep) no longer lets someone act as that page's user: events on a signed-in page also need that user's session. The session hand-off refuses cross-site claims (login CSRF).
- **Limits** on event size (`max_event_mb`, default 1), WebSocket message queues and pending uploads (`max_pending_uploads_mb`, default 256).
- **Security headers:** `X-Frame-Options: SAMEORIGIN` (against clickjacking; `{"domino": {"frame_options": false}}` turns it off), `X-Content-Type-Options: nosniff` and `Referrer-Policy: strict-origin-when-cross-origin`.

### Fixes
- `<pre>` and `<textarea>` content is no longer indented by the renderer.

## 0.2.0

The first big release: Domino becomes a full framework, Meteor-style but all Python.

### Components and rendering
- `State()` attributes: change one and the component re-renders. Handlers no longer need `return self`.
- `on_click=` (and any `on_<event>=`), `debounce=`, `class_=`, `for_=`, `aria_*`/`data_*` attributes, `style` dicts.
- Live inputs: `event.value` and `event.form` arrive typed as the browser sent them; fields keep what the user typed while updates are patched in place.
- Loading states (`[data-loading]`, `aria-busy`) and a debug error overlay.
- Component styles: class-level `css` (nested selectors, `:hover`, `@media`, plain CSS), written once per page; `page.theme()` with a dark variant.
- Templates: t-strings (`html(t"...")`, Python 3.14) parsed into elements, and Jinja templates found by name anywhere in the app, paired with components (`counter.py` + `counter.html`).
- Forms: `domino.forms` — declare fields once; browser checks, server validation, inline errors, typed values.
- File uploads: `event.files`, progress you can style with CSS.

### Reactivity and data
- Meteor-like reactive data: `Collection()` in memory, `Collection("name")` in MongoDB with change streams, so every open page updates live — across processes too.
- Server push: `component.refresh()` from anywhere, e.g. a background thread.
- Instant UI: handlers that only change their own state show at once, any number of clicks in a row, even on a slow connection; the server stays the source of truth.

### Pages and navigation
- File-based routing: `pages/index.py` is `/`, `pages/users/[id].py` is `/users/<id>`, `layout.py` wraps pages, `404.py`.
- Page switches without reloading: links swap pages in place, back/forward work, one connection per visit.
- Accounts: sign-up, login, logout, `current_user()`, `login_required`, GitHub and Google login.

### Server
- One WebSocket per tab when served over ASGI (uvicorn); plain WSGI still works with HTTP + Server-Sent Events.
- Less over the wire: the socket sends a re-rendered component as a patch of what changed (a chat message appended to 200: 28 KB to 200 bytes), large predicted states too; hidden tabs pause, and get one update per changed component when shown; `ws_compression` setting.
- `domino serve --workers N`: every CPU core, with a router that sends each tab to the process that has its page — no sticky sessions.
- Settings: `settings.json` + `settings.local.json` + `DOMINO_*` environment variables; `public` settings readable in the browser.
- Development MongoDB started automatically, like `meteor run`.
- `domino run`, `domino create`, `domino serve`.

### Testing
- `app.test_page()`: a simulated browser for plain pytest — click, type, submit, upload — about a millisecond per click.
- Tests next to their page: `pages/about_test.py` gets a `page` fixture.
- MongoDB under pytest, like `meteor test`: started on demand, an empty database per test.

### Examples
Every example is a folder with `pages/`, runnable from any directory, most with tests next to their pages: counter, todo, search, forms, chat, accounts, uploads, instant, styles, templating, functional (multi-page), clock, loading, settings, showcase and more.

## 0.1.0

First release on PyPI as `domino-web`.
