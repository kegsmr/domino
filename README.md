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
