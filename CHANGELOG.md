# Changelog

## Unreleased

### Developer tools (debug mode only)
- An error page for pages that fail to render: source around each frame, the component stack, the request and hints for common mistakes.
- The event error overlay shows the frames' source, the component stack, hints, and which element and handler fired.
- A component inspector (Alt+Shift+D or `Domino.inspect()`): State kept up to date, events and why a handler isn't instant, subscriptions, parents and children; and an event log with server time, round trip, sizes and whether predictions matched.
- Startup warnings about in-memory `Collection()`s. Production pages are unchanged, byte for byte.

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
