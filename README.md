# Domino

An experimental Python web framework built on Flask. It currently resembles a glorified HTML/CSS generator, but more features are planned.

**This project is a work-in-progress! Not all features are functional yet.**

## Install

The distribution is named `domino-web`; the import name is `domino`.

```
pip install -e .
```

## Run an example

From the repository root:

```
python examples/counter.py
```

Then open http://127.0.0.1:5000.

## Command line

Installing the package adds a `domino` command, modeled on `meteor`:

```
domino create myapp
cd myapp
domino run
```

`domino create <name>` makes a folder with a small reactive app (`app.py`), a `settings.json` with a `public` block, and a `.gitignore`. It won't write into a folder that isn't empty.

`domino run [app.py] [--port 5000] [--host 127.0.0.1] [--no-mongo] [--mongo-version 7.0]` runs the app (default `app.py` in the current folder) in debug mode with the reloader, so it restarts when you save a file. `domino --version` prints the version.

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

Submit events don't reload the page. See `examples/todo.py`.

`bind(event, callback, debounce=ms)` waits until the user pauses before sending, which suits `"input"` events (see `examples/search.py`). An element can have several events.

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

See `examples/loading.py`.

### Server push

`component.refresh()` re-renders a component and sends it to every open page showing it, without waiting for a browser event. It can be called from anywhere, including a background thread. Mark components that will be refreshed with the class attribute `live = True`: pages showing one receive updates over Server-Sent Events from `/_domino/stream`, which keeps one connection (and, on a threaded server, one thread) open per tab, so other pages don't open a stream at all. A component shown on several pages is rendered once per refresh. See `examples/clock.py`.

### Reactive data

Like Meteor, Domino components re-render themselves when the data they show changes. Reading a `State` or querying a `Collection` inside `render()` subscribes the component; changing it re-renders every subscribed component on every open page and pushes the result (no `live = True` needed):

```python
from domino import Collection, State

messages = Collection("messages")   # shared by everyone
online = State(0)

class Chat(t.div):

	def render(self):
		self([t.li() [m["text"]] for m in messages.find(sort=[("sent", -1)], limit=50)])

	def send(self, event):
		messages.insert({"text": event.form["text"], "sent": time.time()})  # every Chat updates
		return self
```

- `State(value)`: `.value` reads (and subscribes), `.value = x` changes it.
- `Collection(name)`: `insert(doc)` (returns the `_id`), `find(query, sort=..., limit=...)` (a cursor you iterate or `.fetch()`), `find_one`, `count`, `update(query, {"$set": ...}, multi=False)` and `remove(query)`, with MongoDB-style queries (`$gt`, `$in`, `$or`, dotted paths, ...). Documents come back as copies.
- Changes made while handling an event re-render each subscriber once, in the background, so the user who made the change gets their response straight away. Use `with batch():` to group changes made elsewhere, and `domino.wait()` in tests to let background updates finish.

See `examples/chat.py`.

### MongoDB

Like Meteor, named collections live in MongoDB: `Collection("messages")` is the `messages` collection of the app's database, and `Collection()` without a name is an in-memory collection for this process only. Queries and updates use MongoDB's own syntax (all of it, not just the subset the in-memory collection supports). Documents get a string `_id` unless they have one.

The database comes from the `mongo.url` setting (e.g. `DOMINO_MONGO__URL=mongodb://db:27017/myapp?replicaSet=rs0`), with the database name taken from the URL (default `domino`); `MONGO_URL` works too, and `domino.mongo.connect(url)` sets it in code. When MongoDB runs as a replica set, a change stream per collection re-renders subscribers when *any* process changes the collection — another server process, a script, or `mongosh` — so it also works with several server processes. Without a replica set only this process's own writes update pages live.

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

`app.test_page(path)` loads a page in a simulated browser, so you can test your app in plain pytest, with no real browser and no server running. Clicks, typing and form submits go through the same code as in a real browser: handlers, `State`, collections and pushed updates all run for real.

```python
from counter import app

def test_counter():
	page = app.test_page("/")
	page.click("button", text="Increment")
	assert page.text("p") == "Current Count: 1"

def test_todo():
	page = app.test_page("/todo")
	page.fill("input[name=text]", "Buy milk")
	page.click("button", text="Add")      # a submit button submits its form
	assert page.text("ul") == "Buy milk"
	assert page.value("input[name=text]") == ""
```

Each test page is its own browser tab. Find elements with simple CSS selectors (`tag`, `.class`, `#id`, `[attr=value]`, and descendants like `form input`), optionally narrowed with `text=`. Pages can be driven with `click`, `fill` (set a value without firing events), `type` (fires `input`), `select`, `check`, and `submit`. Inspect them with `text`, `value`, `find`/`find_all` and `html`. `sync()` applies changes other pages pushed to this one, and `run_timers()` fires pending `after()` timers right away. A failing handler, or a selector that matches nothing, fails the test with the traceback and the page's text. See [examples/test_examples_headless.py](examples/test_examples_headless.py).

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
