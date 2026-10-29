# Testing

Tests that sit next to the page they test, and drive it like a user would, in about a millisecond per click.

## A test file next to the page

Tests for `pages/index.py` go in `pages/index_test.py`. Each test function that takes a `page` argument gets that page, open in a simulated browser: no server to start, no browser to install, nothing to import.

{{ file: 7-testing/pages/index_test.py }}

`page.fill()` types into a field, `page.click()` clicks (a submit button submits its form), and `page.text()` and `page.value()` read what's shown. `page.load()` goes to another page, following redirects and keeping cookies, so signing up carries over. `open_page()` opens another tab, and `sync()` applies what the server pushed to it, which is how the last test checks that a new task shows up live elsewhere.

Clicks and submits go through the same code as in a browser: your handlers, the collections and the pushed updates all run for real.

## Run them

Install pytest and run it in the app's folder:

```bash
pip install pytest
cd tasks
pytest
```

The tests use named collections, so like `meteor test`, Domino starts a MongoDB for the test session (the same cached download as `domino run`), and gives each test an empty database of its own, dropped after it. Tests that only use `State` or `Collection()` never start it.

These very tests run with Domino's own test suite, so this step's code can't stop working without someone noticing. See [Testing](../guide/testing.md) for the rest of the API.
