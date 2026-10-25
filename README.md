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

## Attributes

Keyword arguments become HTML attributes; underscores turn into hyphens (`aria_label` → `aria-label`, `data_user_id` → `data-user-id`). A trailing underscore avoids Python keywords (`for_` → `for`). `class_` (a string or list) adds CSS classes after the component's own, and `style` accepts a dict:

```python
t.button(class_="btn btn-primary", aria_pressed="false", style={"font_weight": "bold"})
```

## Events

`element.bind("click", callback)` runs `callback` on the server and re-renders the component it returns. A callback that takes an argument receives an `Event`:

- `event.type`: the DOM event name (`"click"`, `"submit"`, `"change"`, ...)
- `event.value`: the element's value (`True`/`False` for checkboxes)
- `event.form`: the surrounding `<form>`'s fields as a dict (repeated names become lists)

Submit events don't reload the page. See `examples/todo.py`.

`bind(event, callback, debounce=ms)` waits until the user pauses before sending, which suits `"input"` events (see `examples/search.py`). An element can have several events.

Updates are patched into the page in place rather than replacing the component's HTML, so focus, the caret and anything the user is typing survive a re-render. Form fields keep what the user entered unless the server changes their value, or they belong to the element whose event was just handled (a submitted form is reset to what the server renders).

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
