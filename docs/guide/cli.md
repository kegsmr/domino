# Command line

domino create, run, serve, build and deploy.

Installing the package adds a `domino` command:

```
domino create myapp
cd myapp
domino run
```

`domino create <name>` makes a folder with a small reactive app: a tiny `app.py`, the page `pages/index.html` in the layout `layouts/main.html`, components in `components/` (their logic in `tasks.py`, their markup in `tasks.html`, see [Templates](templates.md#templates)), a `Collection` in `data.py`, a test for the page in `pages/index_test.py` (run it with `pytest`; see [Testing your app](testing.md#testing-your-app)), a `settings.json` with a `public` block, and a `.gitignore`. It won't write into a folder that isn't empty.

`domino create <name> --minimal` makes the smallest app that runs instead: `app.py` and one page, `pages/index.py`, with a counter component (its markup in `pages/index.html`). It keeps its data in `State` only, so its `settings.json` turns the [development MongoDB](#development-mongodb) off and `domino run` starts at once, with nothing to download.

`domino run [folder or app.py] [--port 5000] [--host 127.0.0.1] [--no-mongo] [--mongo-version 7.0]` runs the app (default: the current folder) in debug mode, with [hot reloading](#hot-reloading): saving a file in the app's folder updates the open pages in place. For a folder it runs its `app.py`; a folder with only `pages/` (and maybe `settings.json`) needs no `app.py` at all, as `domino run` makes the app itself. `--port 0` picks a free port. `domino --version` prints the version.

`domino serve [folder or app.py] [--workers N] [--port 8000] [--host 127.0.0.1]` serves the app in production, on every CPU core; see [Serving in production](deployment.md#serving-in-production).

`domino build [folder] [--force]` writes a `Dockerfile` for the app, and `domino deploy fly|render|docker [folder] [--name NAME] [--mongo-url URL] [--force]` deploys it; see [Deploying](deployment.md#deploying).

`domino tailwind build [folder or app.py]` builds an app's minified Tailwind CSS before deploying, and `domino create myapp --tailwind` makes an app styled with Tailwind; see [Tailwind CSS](tailwind.md#tailwind-css).

`app.run(debug=True)` (what `python app.py` does in the examples) serves the same way as `domino run`. The app is served by a process of its own, which loads it again from its file, so the app must be assigned at the top level of the module (`app = Domino(__name__)`); otherwise it runs without reloading. Without debug mode, `app.run()` serves with uvicorn without reloading.

## Hot reloading

While you work on an app with `domino run` or `app.run(debug=True)`, saving a file updates the open tabs in place, usually within about 100 ms: components keep their `State` (the counter's count, which tab is open), and the page keeps what's typed in its fields, focus and scroll position. The server logs a line for each change:

```
domino: hot reloaded components/counter.py (2 pages) in 12 ms
```

- A changed module (a component, a page, a layout, `data.py`, ...) is run again in place, and so are the app's modules that import it. Components on open pages switch to the new classes and are rendered again with the state they had: a `State` attribute added since starts at its default, one removed is dropped. The components their `render()` makes are new, as whenever they're rendered.
- A changed page or layout makes the page again with its new code; components in the same places (the first `Counter`, and so on) take over the state of the old ones. Pages added or deleted get or lose their routes.
- `State` and `Collection` objects at a module's top level are kept, with their values, when it's run again.
- Templates (Domino and Jinja) and component CSS are updated in place too; a template page added to or deleted from `pages/` gets or loses its route. Stylesheets in the app's folder are fetched again; a changed `.js` file reloads the page.
- A syntax error, or any error while reloading, shows in the open tabs (the debug overlay, with the traceback) and the old code keeps running; the next save that works clears it.
- Pages are made again for the current URL with the cookies they were loaded with, so they work with logins.

Some changes can't be swapped in safely, so the server restarts instead (`domino: restarting: app.py changed`) and the open tabs reload by themselves once it's back: `app.py` (or any module that imports it), `settings.json` and `settings.local.json`, a deleted module, and modules that start threads, processes or apps, or add routes, when they're imported, since running them again would do it twice. That last one is a guess from the module's code (calls such as `threading.Thread(...).start()`, `Domino(...)` or `@app.route` outside functions; see `domino/hot.py`); a module can decide for itself with `__hot_reload__ = False` (always restart) or `__hot_reload__ = True` (always hot reload). Files outside the app's folder (Domino itself, installed packages) aren't watched; restart for those.

`{"domino": {"hot_reload": false}}` in `settings.json` restarts the server on every change instead, as uvicorn's reloader does. Production servers (`domino serve`, `app.run()` without debug mode) never watch files.

## Development MongoDB

Running an app in debug mode starts a local MongoDB for it, unless its settings already have `mongo.url`. This happens with `domino run`, and also with `app.run(debug=True)` (or `FLASK_DEBUG=1`, or `app.debug = True`). Importing the app, `flask run` and production servers never start one. Page tests get one of their own (see [MongoDB in tests](testing.md#mongodb-in-tests)).

- The first time, the newest MongoDB 7.0 release built for your OS and CPU is downloaded from mongodb.org (about 100MB), checked against its published SHA-256, and only `mongod` is kept, in `~/.domino/mongodb/<version>/`. Set `DOMINO_HOME` to keep it somewhere else. Later runs use the cached binary and work offline. `--mongo-version` (or the setting `mongo.version`) picks another release series, such as `8.0`.
- `mongod` listens on 127.0.0.1, on the app's port + 1 (5001 for 5000), or on any free port if that one is busy. Its data goes in `.domino/db` in the app's folder and its log in `.domino/mongod.log`. Add `.domino/` to your app's `.gitignore` (`domino create` does).
- It runs as a single-node replica set (`rs0`), which change streams need.
- The URL, `mongodb://127.0.0.1:5001/<app folder name>?replicaSet=rs0&directConnection=true`, is put in `app.settings.mongo.url` and the `DOMINO_MONGO__URL` environment variable before the server starts, so the reloader's process uses the same database.
- `mongod` stops when the app does (Ctrl+C, or the process being terminated). On Linux it also stops if the app is killed. A second `domino run` of the same app reuses the running `mongod`, and a lock left by one that crashed is cleared.
- To turn it off, pass `--no-mongo`, set `DOMINO_NO_MONGO=1`, or set `{"mongo": {"auto": false}}` in `settings.json`.
- If the download fails (offline, or a proxy blocks mongodb.org), point `mongo.url` at a MongoDB you run instead, or turn it off. For a certificate error on macOS, see [Install](installation.md#install).

In production, point the app at your database with the `mongo.url` setting, usually from the environment: `DOMINO_MONGO__URL=mongodb://...`. Without debug mode nothing is downloaded or started.

The development MongoDB needs `pymongo`, which is installed with Domino.
