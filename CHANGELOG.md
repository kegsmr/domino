# Changelog

## 0.3.0

### Development
- Hot reload that keeps state, like React Fast Refresh: save a component, page or template and open pages update in place in about 100 ms, keeping State, typed text and focus. Changes that can't be swapped safely (app.py, settings) restart the server.
- Developer tools (debug mode only): an error page for pages that fail to render (source around each frame, the component stack, hints); a richer event error overlay; a component inspector (Alt+Shift+D or `Domino.inspect()`) with live State, events and why a handler isn't instant; an event log with timings. Production pages are unchanged, byte for byte.
- `python -m domino` runs the `domino` command (handy on Windows). CI also runs on Windows.
- Windows fixes: `[id=int].py` page files (colons can't be in Windows file names), hot reload restarts after `app.py` changes, client components on another drive, and paths in error pages.

### Deploying
- `domino build` writes a Dockerfile (non-root, health check, `domino serve`), `.dockerignore` and `requirements.txt`.
- `domino deploy fly|render|docker`: fly.toml and secrets through flyctl, render.yaml, or a docker-compose.yml with MongoDB as a replica set.
- `/_domino/health`, and `domino serve` reads `WEB_CONCURRENCY`.

### Accounts and email
- `domino.mail`: SMTP, a console backend while debugging, and an outbox under pytest (`mail_outbox` fixture).
- Password reset, email verification (`login_required(verified=True)`) and changing the password. The login and sign-up forms are built on `domino.forms`.

### Styles
- Tailwind CSS with zero setup: `{"tailwind": true}` (or a `tailwind.css` in the app's folder) and classes work anywhere. Tailwind's standalone CLI is downloaded once into `~/.domino/tailwind/`; `domino run` rebuilds as files change and open pages swap in the new CSS; `domino serve` builds it minified; `domino tailwind build` for Dockerfiles; `domino create --tailwind`.

### Speed
- Over the WebSocket, updates are sent as line-diff patches against what the tab already has: a chat message to a 200-message list goes from 28 KB to 198 bytes. Large predicted states are patched too.
- Hidden tabs pause: the server skips their updates until they're shown again.
- `{"domino": {"ws_compression": false}}` saves ~43 KB per idle tab.

### Documentation
- A documentation site built with Domino (`docs/`, `python docs/app.py`): a tutorial with live demos, and guide pages made from the README.

### Experimental
- Client components: `client = True` runs a component in the browser on MicroPython (or Pyodide), server-rendered first, working offline once loaded. See `docs/research/client-python.md`.

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
