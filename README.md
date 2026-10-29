# Domino

An experimental Python web framework for live web apps, built on Flask. Write components with their logic in Python and their markup in HTML. Data updates every open page as it changes, and clicks show their result at once. There's no JavaScript to write.

**This project is a work-in-progress! Not all features are functional yet.**

## Quick start

Domino needs Python 3.9 or newer, on Linux, macOS or Windows.

```
pip install domino-web
domino create myapp
cd myapp
domino run
```

Open http://127.0.0.1:5000. If `domino` isn't found, use `python -m domino run`. See [Installation](docs/guide/installation.md) for more.

For the smallest app that runs, one page with a counter and no database, use `domino create myapp --minimal`.

## A taste

A component is a Python class for its logic and an HTML template for its markup:

```python
# components/counter.py
from domino import State
import domino.tags as t


class Counter(t.div):

    count = State(0)


    def increment(self):

        self.count += 1
```

```html
<!-- components/counter.html -->
<component name="Counter">
    <p>Count: {{ count }}</p>
    <button on-click="increment">+1</button>
</component>
```

Each file in `pages/` is a page, at the URL of its path. This one goes in the layout `layouts/main.html`:

```html
<!-- pages/index.html: the page at / -->
<page layout="Main" title="Home">
    <p>Click to count.</p>
    <Counter />
</page>
```

Clicking the button runs `increment` on the server, and only what changed is updated in the browser.

## Features

- **Components in Python and HTML.** [State](docs/guide/state.md) re-renders what shows it, [events](docs/guide/events.md) are Python methods, and [templates](docs/guide/templates.md) are plain HTML with `{{ for }}` and `{{ if }}` blocks.
- **Live data.** A [Collection](docs/guide/reactive-data.md) is a MongoDB collection that re-renders every open page showing it when it changes, from any process. [Server push](docs/guide/server-push.md) updates pages from a background thread.
- **Instant clicks.** Handlers that only change their component's state [show at once](docs/guide/instant-ui.md), even on a slow connection, with nothing to configure.
- **Pages and layouts.** [File-based routing](docs/guide/pages.md), with page switches that don't reload.
- **Batteries included.** [Forms](docs/guide/forms.md) checked in the browser and on the server, [accounts](docs/guide/accounts.md) with GitHub and Google login, [email](docs/guide/email.md), [file uploads](docs/guide/uploads.md), scoped [styles](docs/guide/styles.md) and [Tailwind](docs/guide/tailwind.md) with nothing to install.
- **Development.** [Hot reloading](docs/guide/cli.md), a development MongoDB downloaded for you, and [developer tools](docs/guide/devtools.md) in the page.
- **Tests next to their page.** `pages/about_test.py` tests `pages/about.py` in a [simulated browser](docs/guide/testing.md), in about a millisecond per click.
- **One-command deploys.** [`domino deploy`](docs/guide/deployment.md) to Fly.io, Render or Docker, and `domino serve` uses every CPU core.
- **Desktop apps.** [`domino desktop`](docs/guide/desktop.md) shows an app in a native window, and `domino build --desktop` packages it with PyInstaller.
- **Experimental:** [client components](docs/guide/client-components.md) that run in the browser, in Python.

## Learn more

- [The tutorial](docs/tutorial/1-first-page.md) builds an app step by step.
- [The guide](docs/README.md) covers each feature.
- [The examples](examples/README.md) are small apps: run one with `python examples/counter/app.py`.
- [How it works](docs/guide/how-it-works.md): one WebSocket per tab.

The documentation is also a website, built with Domino: run `python website/app.py`.

## Contributing

```
pip install -e .[test]
python -m pytest
```

See [Contributing](docs/guide/contributing.md) for MongoDB tests and releases.

## License

MIT, copyright (c) 2026 Kegan Messmer. See [LICENSE.txt](LICENSE.txt).
