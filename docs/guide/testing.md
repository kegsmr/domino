# Testing

Tests next to their page, in a simulated browser.

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

Find elements with simple CSS selectors (`tag`, `.class`, `#id`, `[attr=value]`, and descendants like `form input`), optionally narrowed with `text=`. Pages can be driven with `click`, `fill` (set a value without firing events), `type` (fires `input`), `select`, `check`, `submit`, `trigger` (any other event: `page.trigger("li", "pointerdown")`), and `upload` (picks files in a file input and fires its `change`; each file a path or `(filename, bytes[, content_type])`, e.g. `page.upload("input[name=photo]", ("me.png", data))`; they're uploaded with that event and with the form's submit, as in a browser). Inspect them with `text`, `value`, `find`/`find_all`, `html`, `status` and `path`. `sync()` applies changes other pages pushed to this one, `run_timers()` fires pending `after()` timers right away, and `load(path)` navigates (redirects are followed and cookies kept, like a browser, so a login carries over). A failing handler, or a selector that matches nothing, fails the test with the traceback and the page's text.

Outside `pages/`, `app.test_page(path)` gives the same simulated browser for any app. See the examples' `pages/*_test.py`, e.g. [examples/counter/pages/index_test.py](../../examples/counter/pages/index_test.py), [examples/chat/pages/index_test.py](../../examples/chat/pages/index_test.py) (two windows) and [examples/accounts/pages/private_test.py](../../examples/accounts/pages/private_test.py) (signing up and logging out).

## MongoDB in tests

Pages with named Collections can be tested with nothing to set up. The first time a test that uses `page` or `open_page` connects to MongoDB, a `mongod` is started for the test session (the same cached download as `domino run`'s, on a free port, with its data in a temporary folder, so your development database in `.domino/` is never touched), and it's stopped when the session ends. Tests that don't use named Collections never start it.

- Each test gets an empty database of its own (`domino_test_<session>_<n>`), dropped in the background after the test. Collections switch to it by themselves, and change streams follow, so changes from one test never reach the next. `sync()` waits for the change stream to announce this process's writes, so a second tab sees them straight away. The overhead is about a millisecond per test.
- The `domino_db` fixture gives the same database (as a pymongo `Database`) to any test, including tests that use collections directly: `def test_import(domino_db): ...`.
- To use a server you run instead (e.g. in CI), set `DOMINO_TEST_MONGO_URL=mongodb://127.0.0.1:27017/?replicaSet=rs0`; nothing is started then. A `mongo.url` setting (or `DOMINO_MONGO__URL`) is used the same way. Either way, tests only create and drop their own databases on it, never the one the URL names. Use a replica set, so pages update live.
- To turn it off, pass `pytest --no-mongo`, set `DOMINO_NO_MONGO=1`, or set `{"mongo": {"auto": false}}`. A test that uses a named Collection then fails with a message saying so. If `mongod` can't be downloaded or started (offline, say), tests that need it fail with the reason and a pointer to `DOMINO_TEST_MONGO_URL`.
- With pytest-xdist, each worker starts its own `mongod`, or shares the `DOMINO_TEST_MONGO_URL` server with databases of its own.
