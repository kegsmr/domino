# Domino

An experimental Python web framework built on Flask. It currently resembles a glorified HTML/CSS generator, but more features are planned.

**This project is a work-in-progress! Not all features are functional yet.**

**Documentation:** the [docs site](docs/README.md) has a step-by-step tutorial with live demos and a guide made from this README. It's a Domino app itself: run `python docs/app.py` and open http://127.0.0.1:5000.

## Install

The distribution is named `domino-web`; the import name is `domino`.

```
pip install -e .
```

## Run an example

```
python examples/counter/app.py
```

Then open http://127.0.0.1:5000. Each example is a folder with a small `app.py` and its pages in `pages/`; see [examples/README.md](examples/README.md).

## Pages

Each Python file in the app's `pages/` folder is a page, and its path is the URL:

```
myapp/
  app.py                 app = Domino(__name__)
  pages/
    index.py             /
    about.py             /about
    contact.html         /contact, a template page (see Templates)
    users/
      index.py           /users
      [id].py            /users/<id>
      [id]/posts.py      /users/<id>/posts
    docs/[...path].py    /docs/<path:path>, the rest of the URL
    layout.py            wraps every page in its folder and below
    404.py               the page for URLs no page serves
    _helpers.py          not a page: names starting with _ are private
  components/            components the pages import
  data.py                Collections the pages import
  settings.json
```

A page file defines `page()`, returning anything a route can: a component, a `Document`, a string or a Flask response. The parts of the URL in brackets arrive as keyword arguments. `[int:id].py` uses Flask's `int` converter (`float`, `uuid` and `path` work too), and `[...path].py` matches the rest of the URL, slashes included (at least one segment: `/docs` itself needs `docs/index.py`).

```python
# pages/users/[int:id].py  ->  /users/42
import domino.tags as t


def page(id):

	return t.h1() [
		f"User {id}"
	]
```

A page can also be a component class named `Page`. Each visit gets a new one, and the URL's parameters are passed to its `init(self, ...)`:

```python
# pages/counter.py  ->  /counter
from domino import State
import domino.tags as t


class Page(t.div):

	count = State(0)


	def render(self):

		return [
			t.button(on_click=self.increment) [
				f"Clicked {self.count} times"
			]
		]


	def increment(self):

		self.count += 1
```

`layout.py` defines `layout(content)` and returns the page wrapped in whatever every page shares, usually a `Document` with the navigation. Layouts nest: the `pages/` folder's own layout is the outermost, then each subfolder's, down to the page's own folder. A layout that names URL parameters (`layout(content, id)`) receives them.

```python
# pages/layout.py
import domino.tags as t
from domino.components import Document


def layout(content):

	return Document(title="My site") [
		t.nav() [
			t.a(href="/") ["Home"],
			t.a(href="/about") ["About"]
		],
		content
	]
```

- A page that returns a whole document (a `Document`, or any `t.html`) or a Flask response is used as it is, without layouts.
- A component that no layout puts in a document is put in a plain `Document()`, which loads Domino's script, so its events work.
- `404.py`'s `page()` is shown, inside the layouts and with status 404, for URLs no page or route serves, and for `abort(404)`.
- The app's folder is on the import path, whatever the current folder is, so pages can `from components.chat import Chat` and `from data import messages`. Pages are imported while the app is created, so they can't import `app.py`; read settings with `flask.current_app.settings`.

Pages are on when the app's folder (the folder of the module passed to `Domino(__name__)`) has a `pages/` folder. `Domino(__name__, pages="views")` uses another folder and `pages=False` turns them off. `@app.route` keeps working alongside pages; a route for a URL a page already serves is an error, naming both, when the app starts. Pages are found once, when the app is created, and each file is imported once; while debugging, [hot reloading](#hot-reloading) swaps in pages that change and adds or removes the routes of pages added or deleted. Pages render exactly like `@app.route` views, with events, reactive data and server push.

### Moving between pages

Clicking a link to another page of the app swaps that page in without reloading, like a single-page app, with nothing to write: Domino fetches the page as usual (a normal GET, marked with an `X-Domino-Navigate: 1` header), morphs the document into it, keeping the nodes that stay the same (the layout's navigation, say), and adds the URL to the history, so back and forward work too. The title, `<head>` styles and component CSS follow the new page, and scripts it adds run. Domino's script and the tab's WebSocket stay, so the new page's events work right away; its `after()` timers start, the page scrolls to the top (or to the link's `#hash`, or back where it was for back/forward), focus moves to its main heading, and its title is announced to screen readers. The page left is dropped on the server at once.

- Redirects on this site are followed, ending at the final URL (e.g. a `login_required` page sends you to `/login?next=...`). `domino.redirect()` in an event handler goes the same way.
- Anything else loads as usual: links to other sites, a response that isn't a Domino page (or a network error), links with `target`, `download` or a modifier key (to open a new tab), and `#hash` links within the page.
- While the page loads, `<html>` has `data-domino-loading` and the clicked link `aria-busy`/`data-loading`, as for events; a click on another link cancels it. The latency simulator applies too.
- `data_domino_reload=True` on a link, or any element around links, makes them load from scratch; `{"domino": {"navigation": false}}` does this for the whole app.
- Each page shown is a new page load as far as your code is concerned: components start fresh, as on a reload.

## Command line

Installing the package adds a `domino` command, modeled on `meteor`:

```
domino create myapp
cd myapp
domino run
```

`domino create <name>` makes a folder with a small reactive app: a tiny `app.py`, `pages/index.py` and `pages/layout.py`, components in `components/` (their logic in `tasks.py`, their markup in `tasks.html`, see [Templates](#templates)), a `Collection` in `data.py`, a test for the page in `pages/index_test.py` (run it with `pytest`; see [Testing your app](#testing-your-app)), a `settings.json` with a `public` block, and a `.gitignore`. It won't write into a folder that isn't empty.

`domino run [folder or app.py] [--port 5000] [--host 127.0.0.1] [--no-mongo] [--mongo-version 7.0]` runs the app (default: the current folder) in debug mode, with [hot reloading](#hot-reloading): saving a file in the app's folder updates the open pages in place. For a folder it runs its `app.py`; a folder with only `pages/` (and maybe `settings.json`) needs no `app.py` at all, as `domino run` makes the app itself. `--port 0` picks a free port. `domino --version` prints the version.

`domino serve [folder or app.py] [--workers N] [--port 8000] [--host 127.0.0.1]` serves the app in production, on every CPU core; see [Serving in production](#serving-in-production).

`domino build [folder] [--force]` writes a `Dockerfile` for the app, and `domino deploy fly|render|docker [folder] [--name NAME] [--mongo-url URL] [--force]` deploys it, like `meteor deploy`; see [Deploying](#deploying).

`domino tailwind build [folder or app.py]` builds an app's minified Tailwind CSS before deploying, and `domino create myapp --tailwind` makes an app styled with Tailwind; see [Tailwind CSS](#tailwind-css).

`app.run(debug=True)` (what `python app.py` does in the examples) serves the same way as `domino run`. The app is served by a process of its own, which loads it again from its file, so the app must be assigned at the top level of the module (`app = Domino(__name__)`); otherwise it runs without reloading. Without debug mode, `app.run()` serves with uvicorn without reloading.

### Hot reloading

While you work on an app with `domino run` or `app.run(debug=True)`, saving a file updates the open tabs in place, usually within about 100 ms, like React's Fast Refresh: components keep their `State` (the counter's count, which tab is open), and the page keeps what's typed in its fields, focus and scroll position. The server logs a line for each change:

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

### Development MongoDB

Like `meteor run`, running an app in debug mode starts a local MongoDB for it, unless its settings already have `mongo.url`. This happens with `domino run`, and also with `app.run(debug=True)` (or `FLASK_DEBUG=1`, or `app.debug = True`). Importing the app, `flask run` and production servers never start one. Page tests get one of their own (see [MongoDB in tests](#mongodb-in-tests)).

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

## Styles

A component declares its styles on the class, with `css`. They are scoped to its class name and written into the page's `<head>` once, however many times the component is shown:

```python
class Card(t.div):

	css = {
		"padding": "1rem",                              # .Card
		"background": "var(--surface)",
		"h3": {"margin": 0},                            # .Card h3
		":hover": {"box_shadow": "0 2px 8px #0002"},    # .Card:hover
		"& + &": {"margin_top": "1rem"},                # .Card + .Card
		"@media (max-width: 600px)": {"padding": ".5rem"},
	}
```

- Property names are written with underscores (`font_size`); `__accent` (or `"--accent"`) is the CSS variable `--accent`. Values are written as given (no units are added), and `None` leaves a property out.
- A nested key is a selector. Keys starting with `:` or `[` (`":focus"`, `"::after"`, `"[open]"`) attach to the enclosing selector, other keys (`"h3"`, `"> li"`, `"input, textarea"`) select descendants, and `&` stands for the enclosing selector anywhere (`"&.active"`, `"& + &"`). `""` is the component itself.
- `@media`, `@supports`, `@container` and `@layer` blocks hold the same kind of rules; other at-rules, such as `@keyframes` and `@font-face`, are written as they are, unscoped.
- `css` can also be plain CSS, scoped the same way: `css = "& { padding: 1rem } h3 { margin: 0 }"`.
- Subclasses keep their base class's styles (the element has both classes) and add their own, which come later and so win.
- When a component first appears in an event response or a push, its CSS comes with it and is added to the page once.

A page's own rules go on the `Document`, and can be added at any point, including from a component's `render()`, since the page's CSS is computed when it has finished rendering:

```python
page.style("body", font_family="system-ui", margin="2rem auto")
page.style("a", {":hover": {"color": "red"}, "@media print": {"color": "black"}})  # nested, as in css
page.theme(surface="#fff", text="#111", dark={"surface": "#111", "text": "#eee"})  # --surface, --text
```

`theme()` sets CSS variables on `:root`, with the `dark` values for visitors whose system prefers a dark color scheme. Component CSS comes before the page's in the `<head>`, so where both match equally the page wins.

Styles shared by every page can go in a stylesheet the browser caches: `stylesheet = app.style("/style.css")` serves it, `stylesheet.style(...)` adds rules to it (the same as `page.style`), and `stylesheet.link(head)` links it from a page. For a single element, use the `style` attribute (a dict, see Attributes). `stylesheet.style(element, ...)` still works too, but writes a `<style>` block for each element it's used on; for a component shown many times, `css` is much smaller.

CSS can't close the `<style>` element it's written in, whatever the values hold. See `examples/styles/`.

## Tailwind CSS

Turn it on with one setting, and write [Tailwind](https://tailwindcss.com) classes anywhere: on tag classes, in Jinja templates, in template strings. There's no Node, npm, config file or build step:

```json
{"tailwind": true}
```

```python
t.div(class_="rounded-xl bg-white p-6 shadow-sm dark:bg-slate-900") [
	t.h2(class_="text-lg font-semibold") ["Hello"]
]
```

- **Turning it on**: `"tailwind": true` in `settings.json` (or `DOMINO_TAILWIND=true`), or a `tailwind.css` file in the app's folder. `"tailwind": false` turns it off even then. `domino create myapp --tailwind` makes an app styled with it.
- **How it works**: Tailwind's official standalone CLI (Tailwind v4, one executable) is downloaded the first time from its GitHub releases, for your OS and CPU, checked against the release's SHA-256 sums, and kept in `~/.domino/tailwind/<version>/` (or under `DOMINO_HOME`), so later runs work offline. It reads the app's `.py` and `.html` files (skipping `.domino/` and anything `.gitignore` lists) for class names, and writes the CSS for those it finds, and only those, to `.domino/tailwind.css`. Every page links it in its `<head>`, at `/_domino/tailwind.css?v=<hash of the CSS>`: `Document` pages, pages with a `t.head` of their own, and Jinja pages.
- **While debugging** (`domino run`, `app.run(debug=True)`), it's built once at startup, then the CLI keeps running, watching the app's files, and rebuilds when one changes. Open pages hear about it and swap in the new stylesheet without reloading, so a class added in a template shows up as you save it (a `.py` file restarts the server; the CSS is rebuilt meanwhile). The CLI stops with the server, however it stops. Errors in your CSS are printed and the server keeps going.
- **Version**: Tailwind 4.3.3 by default; `{"tailwind": {"version": "4.1.0"}}` picks another release.
- **Offline, or an OS without a build**: if the download fails, the error says so, and pages work without the CSS. Download the CLI for your platform from [Tailwind's releases](https://github.com/tailwindlabs/tailwindcss/releases) yourself and set `DOMINO_TAILWIND_BIN` to its path (or save it where the message says).

### Your own theme

Tailwind v4 is configured in CSS. Without a `tailwind.css`, Domino makes one in `.domino/` that imports Tailwind and points it at the app's files. To customize it, put a `tailwind.css` in the app's folder (or name another file with `{"tailwind": {"input": "styles/app.css"}}`); it's used as it is:

```css
@import "tailwindcss";
@source not ".domino";      /* unless .gitignore lists .domino/ */

@theme {
	--color-brand: #ff6a00;
	--font-display: "Inter", sans-serif;
}
```

`bg-brand` and `font-display` then work like any other class. Tailwind finds classes in the app's folder (the CLI runs there), skipping what `.gitignore` lists; `@source "../shared";` adds a folder.

### Tailwind in production

`domino serve` (and `app.run()` without debug mode) builds minified CSS once at startup, before the workers start, and never watches. If the CLI isn't downloaded but a `.domino/tailwind.css` is there, that one is served, so an image built with the CSS needs no download when it starts. The CSS is served with `Cache-Control: public, max-age=31536000, immutable` at its hashed URL, so browsers download it again only when it changes. Servers that didn't build it (`uvicorn app:app.asgi`, `gunicorn app:app`, `flask run`) build it on the first request for it, if the CLI is already downloaded (or, in debug mode, after downloading it).

`domino tailwind build [folder]` builds the minified CSS into `.domino/tailwind.css` (downloading the CLI if needed): the step to run when building a deploy, e.g. in a Dockerfile, after copying the app in:

```dockerfile
RUN domino tailwind build
```

### Caveats

- Class names must appear in full somewhere in the app's files: Tailwind reads the source, it doesn't run it. `class_="bg-red-500" if error else "bg-green-500"` works; `f"bg-{color}-500"` doesn't, unless each full name is written somewhere (a dict of names, say).
- Tailwind's CSS is all in cascade layers, and CSS outside a layer beats CSS in one, so a component's `css` and `page.style()` rules win over utilities that set the same property. Put the component's rules in a layer (`css = {"@layer components": {...}}`) to let utilities override them, or use Tailwind's `!` (`p-8!`).
- Two utilities for the same property on one element (`text-slate-600 text-indigo-600`) leave the winner to the order of Tailwind's CSS, not of the classes: add one or the other.
- Tailwind's base styles (Preflight) reset margins, headings and buttons on every page of the app.

## Components

A component is a Python class with its markup in HTML. **Markup lives in `.html` templates; Python is for logic and composition**: the class keeps the `State`, the helpers the template reads and the handlers its events call, and the template says what it looks like:

```python
# components/counter.py
from domino import State
import domino.tags as t


class Counter(t.div):

	count = State(0)  # per component, like React's useState


	def increment(self):

		self.count += 1
```

```html
<!-- components/counter.html -->
<Counter>
	<p>Count: {{ count }}</p>
	<button on-click="increment">+</button>
</Counter>
```

Changing state re-renders the component, and only what changed is updated in the browser. A component that only decides *which* components to show writes that in Python, in `render()`, and passes them data and its own handlers:

```python
class Tasks(t.div):

	items = State([])


	def render(self):

		if not self.items:
			return [TaskForm(on_add=self.add), EmptyState()]

		return [TaskForm(on_add=self.add), TaskList(items=self.items)]
```

See [Templates](#templates) for the template syntax. Components can also be written entirely in Python, with tag classes, which suits small pieces and generated markup:

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
- `init(self)` runs once when the component is created, for setup that isn't state.
- The older style, `self([...])` with `element.bind("click", callback)` and `return self`, still works.

### State

`State(value)` holds a value the page shows. Reading it in `render()` subscribes the component, and changing it re-renders every component that read it:

- As a class attribute (`count = State(0)`), each component instance has its own value, like React's `useState`; read and assign it as `self.count`.
- At module level (`online = State(0)`), one value is shared by everyone: `online.value` reads it and `online.value = 3` changes it, re-rendering the components that show it on every open page (see [Reactive data](#reactive-data)).
- Lists and dicts: assign a new value (`self.items = self.items + [x]`) or set them again after changing them in place, since changes inside them can't be seen.
- Each page load, including a page swapped in by a link, makes its components afresh, so their state starts again. Keep what should last, or be shared, in a `Collection`.
- Handlers that only change their own component's `State` show at once in the browser, before the server answers (see [Instant updates](#instant-updates)).

## Templates

Domino templates are plain HTML with three additions: components are capitalized tags, lists and conditions are attributes, and every value comes from Python. There's no logic in them, so there's nothing new to learn beyond HTML, and nothing to debug in them but HTML. See `examples/templating/`.

```html
<!-- components/todos.html -->
<TodoList class="todos">
	<ul>
		<li each="index, item in enumerate(items)" :class="item_class(item)">
			<input type="checkbox" :checked="item.done" on-change="toggle(index)">
			{{ item.text }}
			<button on-click="remove(index)" aria-label="Remove">×</button>
		</li>
		<li else>Nothing to do!</li>
	</ul>
	<p if="remaining">{{ remaining }} left</p>
	<p else>All done.</p>
	<Card heading="Tips"><p>Click an item to finish it.</p></Card>
</TodoList>
```

```python
# components/todos.py
class TodoList(t.div):

	items = State([])


	def remaining(self):                     # a helper: {{ remaining }} calls it

		return sum(1 for item in self.items if not item["done"])


	def item_class(self, item):              # :class takes a string, a list or {class: bool}

		return {"done": item["done"]}


	def toggle(self, index):

		...


	def remove(self, index):

		self.items = self.items[:index] + self.items[index + 1:]
```

**Defining a component.** A capitalized tag at the top level of an `.html` file defines the component of that class: `<TodoList>...</TodoList>` holds `TodoList`'s markup (the class still makes the outer element, here a `<div>`). Attributes on the defining tag go on that element, after what the Python side sets (`class` adds up, other attributes the Python side set win); `as="aside"` makes the element an `<aside>` instead (a class that sets its own `tag` must agree). A file can define several components, Meteor-style, and holds nothing but definitions.

**Where they go.** Put them anywhere in the app; by convention next to the module, with the same name (`todos.py` and `todos.html`). Domino reads every `.html` file of the app's folder at startup (skipping hidden folders, `node_modules`, `site-packages` and `static/`, and pages and Jinja templates, whose top level isn't a definition) and finds each component's definition by its class name. Two definitions of one name stop the app at startup, naming both files, unless two classes of that name in different modules each have theirs next to their module, which then wins. A definition no class is named after is a warning. A class with a `render()` uses that instead.

**Using components.** Anywhere else, a capitalized tag shows a component: `<Counter />`, or `<Card heading="Tips">children</Card>`. They're live like any other: events, `State`, re-renders and instant updates work. Classes are found by name: in the module of the component whose template it is (or, for `template()`, its context and the calling module), then among the app's component classes; one not imported yet is imported from the module next to a file that defines components (or `components/<snake_case name>.py`). An unknown name is an error with the closest names.

- Attributes become what the component declares: a `State` (its starting value), a property with a setter, or a class attribute (`heading = ""`). Plain attributes are strings; `:items="visible"` passes a value. Other attributes (`class`, `id`, `aria-*`, ...) go on its element, as in Python.
- `on-add="add"` passes a handler: if the component declares `on_add = None`, the handler is its prop, which it calls itself (`self.on_add(text)`), and the event then re-renders the parent; otherwise it's a DOM event on the component's element.
- What's between `<Card>` and `</Card>` goes where Card's template has `<slot />` (`<slot>fallback</slot>` shows its own content when there's none). Python composition works the same way: `Card(heading="Tips") [t.p() ["..."]]`.

**Values.** `{{ name }}`, `{{ item.text }}` and `{{ item["text"] }}` read the component's `State`, properties, attributes and helper methods (called without arguments: helpers are how logic stays in Python), and loop variables. `.name` also reads a dict's key, and a missing key is nothing; an unknown name, or an object's unknown attribute, is an error naming the template's file, line and column, with the names that exist. `helper(item, "text")` calls a method with values; `not x` is the one operator. Nothing else: no comparisons, arithmetic or filters, so write a helper (`is_open(index)`, `remaining`).

- Text is escaped; `Markup` values and Domino elements are inserted as they are; `None` and `False` show nothing. In `<script>` values are inserted as JSON.
- Plain attributes are written as they are: `{{ }}` doesn't work in them (it's an error saying what to write instead).

**Lists and conditions** are attributes: `each="item in items"` repeats the element (`each="key, value in prices.items"` unpacks, `enumerate(items)` numbers), `if="name"` shows it when the value is true, and `elif="name"` / `else` on the next elements continue the condition. `else` after an `each` shows when the list is empty. On one element, `each` comes first and `if` filters the items. `<template each="..."> ... </template>` repeats its content without an element of its own.

**Bound attributes**: `:disabled="at_zero"` writes `disabled` when the value is true and leaves it out when it's false or None; other values are written escaped. `:class` takes a string, a list or a dict `{class: bool}`, and adds to `class="..."`; `:style` takes a dict (`{"font_weight": "bold"}`) and adds to `style="..."`.

**Events**: `on-click="increment"` binds a method; `on-click="remove(index)"` binds it with values, so each item of a list gets its own. `on-input="search(event)"` passes the `Event`; `debounce="250"` waits until the user pauses. Handlers that only change the component's own `State` are [instant](#instant-updates), with values too.

**Whitespace** is kept as written: nothing is added around inline elements (`<a>Domino</a>.` has no space before the dot), and `each`/`if` take the line break before their element along, so each item is on a line of its own and a hidden element leaves no empty line.

**Pages.** An `.html` file in `pages/` without a `.py` of the same name is a page: `pages/about.html` is `/about`, inside the layouts, with the URL's parameters as its values (`pages/users/[name].html` reads `{{ name }}`). A page with `<head>` and `<body>` (without `<html>`, like Meteor's `index.html`) or `<html>` is a whole document: Domino adds the doctype, its script and the components' CSS. `template("home.html", title="Home")` renders any template from Python.

**Compiled once.** Each file is parsed once into static HTML strings and the few dynamic parts, so rendering a template does little more than join strings (about as fast as Jinja, faster than tag classes); while debugging, a file that changed is parsed again, and hot reloading updates open pages.

### Jinja or Domino?

Jinja stays available, for pages and existing templates. A file is Jinja when it starts with `{# jinja #}`, ends in `.jinja`, or uses anything only Jinja has (`{% %}`, `{# #}`, filters, operators, `{{ }}` inside an attribute, Jinja's globals such as `url_for`, `component`, `on`); `{"templates": "jinja"}` in the settings reads every page template as Jinja, and `{# domino #}` at the top marks a Domino one. Files that define components (a capitalized tag at the top level) are always Domino templates.

### Template strings (Python 3.14)

`html()` turns a [template string](https://peps.python.org/pep-0750/) (`t"..."`) into the same Domino elements tag classes make, so events, `State`, escaping, instant updates and in-place patching all work as before:

```python
from domino import State, html
import domino.tags as t


class Counter(t.div):

	count = State(0)
	items = State(["a", "b"])


	def render(self):

		return html(t"""
			<p>Count: {self.count}</p>
			<button on_click={self.increment}>+</button>
			<ul>{[html(t"<li>{item}</li>") for item in self.items]}</ul>
		""")


	def increment(self):

		self.count += 1
```

- As text, `{value}` is escaped; an element, or a list of elements and text, becomes children; `None` and `False` render nothing; `Markup` is inserted as it is. Inside `<script>` values are inserted as JSON.
- As an attribute value (`name={value}`, quoted or not), the value is passed like a keyword argument: `on_click={self.increment}` binds the event (`debounce=250` applies), `class={["a", "b"]}`, `style={styles}` with a dict, and `True`/`False`/`None` follow the usual attribute rules. Attribute names are the keyword names with hyphens allowed: `aria-label`, `data-id`, `for`, `class`.
- `<div {attributes}>` spreads a dict of attributes.
- `<{Card} title="x">children</{Card}>` or `<{Card} />` creates a component, with the attributes as keyword arguments.
- Tags are the classes in `domino.tags` (`<div>` is `t.div`); other names, like `<my-widget>`, make a plain element with that tag.
- One root element returns that element; otherwise `html()` returns a list, which works as `render()`'s result and as children.
- Each template is parsed once (cached by its static text), so rendering one only fills in the values. Invalid HTML, such as an unclosed or mismatched tag, raises `TemplateError` with the line number.
- Use `{{` and `}}` for literal braces, as in f-strings. Lambdas need parentheses: `on_change={(lambda: self.remove(index))}`.

Template strings need Python 3.14; on older versions `html()` raises an error saying so (the rest of Domino works from 3.9).

### Jinja templates

Flask's Jinja templates suit layouts and mostly static pages. Domino finds `.html` templates by file name anywhere in the app's folder, like Meteor: `templates/` as in Flask, or next to the code that uses them. Hidden folders, `.domino/`, `static/`, `node_modules/`, `__pycache__/` and virtualenvs are skipped. Since names are looked up without folders, two templates with the same name stop the app at startup with both paths. While debugging, edited and new templates are picked up without a restart.

`template(name, **context)` renders one as an element; return it from a page's `page()` (or a route) to make it the whole page (Domino adds its script, its page id and the CSS of the components inside), or use it as a child. Inside, `{{ component(Counter) }}` (or `{{ component(Counter, title="x") }}`) and `{{ element }}` render live Domino components, whose events and re-renders work as usual; the Jinja part around them is static.

```python
# pages/index.py
def page():

	return template("home.html", title="Home", Counter=Counter)
```

```html
<body>
	<h1>{{ title }}</h1>
	{{ component(Counter) }}
</body>
```

Components can have Jinja templates too, the older way: a component without a `render()` or a Domino definition, whose module has a template next to it named after the class (`TodoList` → `todo_list.html`) or after the module (`counter.py` → `counter.html`), its markup not inside a `<TodoList>` tag, renders that template with Jinja. Its `State` values and methods are available by name, and the component itself as `this` (Jinja keeps `self` for its blocks). `on(click=handler)` binds events, like `on_click=`; it takes several events and `debounce=`. Reading `State` subscribes the component and its handlers are predicted for instant updates, as with `render()`. A `render()` method, when there is one, wins over the template.

```python
# components/counter.py
class Counter(t.div):

	count = State(0)


	def increment(self):

		self.count += 1
```

```html
<!-- components/counter.html -->
<p>Count: {{ count }}</p>
<button {{ on(click=increment) }}>+1</button>
```

Domino templates are the recommended way to write markup; Jinja suits existing templates and pages that need its logic, template strings small pieces of markup inside Python.

## Events

`element.bind("click", callback)` (or `on_click=callback`) runs `callback` on the server. A callback that takes an argument receives an `Event`:

- `event.type`: the DOM event name (`"click"`, `"submit"`, `"change"`, ...)
- `event.value`: the element's value (`True`/`False` for checkboxes)
- `event.form`: the surrounding `<form>`'s fields as a dict (repeated names become lists)
- `event.files`: uploaded files (see [File uploads](#file-uploads))

Submit events don't reload the page. See `examples/todo/`.

`bind(event, callback, debounce=ms)` waits until the user pauses before sending, which suits `"input"` events (see `examples/search/`). An element can have several events.

Updates are patched into the page in place rather than replacing the component's HTML, so focus, the caret and anything the user is typing survive a re-render. Form fields keep what the user entered unless the server changes their value, or they belong to the element whose event was just handled (a submitted form is reset to what the server renders).

### Loading and errors

While an event's request is in flight, the element that fired it gets `aria-busy="true"` and `data-loading` (for a submit, so do the form's submit buttons), and `<html>` gets `data-domino-loading`. Buttons, selects and other controls are also disabled until the response is applied, unless they were disabled already; text fields that fire debounced `input` events are not, so typing continues. Domino adds no styles for this, so add your own:

```python
page.style("button[data-loading]", opacity="0.6", cursor="progress")
page.style("html[data-domino-loading]", cursor="progress")
```

If a callback raises, the server logs the exception and answers with status 500. In production the response only says `"Internal Server Error"`; with `app.debug` on it includes the exception and its traceback, and the browser shows them in an overlay (see [Developer tools](#developer-tools)). Either way the browser dispatches a cancelable `domino:error` event on the element that fired, which bubbles to the document, with `detail` holding `error`, `traceback` (debug only) and `eventId`. Cancel it to handle errors yourself:

```js
document.addEventListener('domino:error', (e) => {
    e.preventDefault();  // no overlay or console.error
    showToast('Something went wrong');
});
```

See `examples/loading/`.

### Developer tools

In debug mode (`domino run`, `app.run(debug=True)`), Domino helps you find what went wrong:

- **A page that fails to render** shows an error page instead of a bare 500: the exception, the traceback with the source around each line (your own frames open and marked, Flask's and Domino's folded), the component stack (`Layout › TodoList › TodoItem`, the one whose `render()` failed last), the request, and hints for common mistakes, like a `MongoNotConfigured` (how to set `mongo.url`) or a `render()` that returns something that isn't an element. A Jinja error shows the template's line.
- **A failing event handler** shows the same in the overlay: which event fired on which element and which handler ran, the frames with their source, the component stack and hints. It closes with its × or Esc.
- **The component inspector**: press <kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>D</kbd> or run `Domino.inspect()` in the browser console, hover a component to outline it, and click it. The panel shows its class and source file, its `State` values (kept up to date as the component re-renders), its attributes, the events it bound and their handlers, whether each is [instant](#instant-updates) and if not, why not (`add() line 70: it reads the event...`), what its last render subscribed to, and its parents and children (click one to inspect it). `Domino.inspect(element)` inspects a given element's component.
- **The event log**, the panel's Events tab: this page's last 50 events, each with its element, handler, time on the server, round trip, size each way, and whether a predicted state was shown and matched the server's answer.
- **Startup warnings**: a debug server warns about module-level `Collection()`s (in memory, so each `domino serve` worker would have its own) and named Collections with no MongoDB to go to.

None of this exists outside debug mode: pages are byte for byte what they'd be without it (the tools are a separate script, `/_domino/debug.js`, linked only from debug pages), and its URLs answer 404. The inspector only shows a page the components it shows, asked with the page's own id. Page tests run with `app.testing` rather than debug mode, so a failing handler or page fails the test with its traceback, as before. See `examples/devtools/`.

### File uploads

A file input works like any other field: its files arrive in the handler as `event.files`, a werkzeug `MultiDict` of uploaded files (werkzeug's `FileStorage`, plus `size` in bytes):

```python
class Avatar(t.div):

	def render(self):
		return [
			t.form(on_submit=self.save) [
				t.input(type="file", name="photo", accept="image/*"),
				t.input(type="file", name="extras", multiple=True),
				t.button() ["Upload"],
			],
			t.input(type="file", name="quick", on_change=self.quick),  # uploads as soon as a file is picked
		]

	def save(self, event):
		photo = event.files["photo"]                 # or event.files.get("photo"), None if none was picked
		photo.filename, photo.content_type, photo.size
		photo.save(path)                             # or photo.read(), photo.stream
		for file in event.files.getlist("extras"):   # a multiple input
			...

	def quick(self, event):
		file = event.files["quick"]
```

- A form's submit sends the files of every file input in it; a file input's own event (`on_change=`) sends its files. Other events (a click inside the form) send none. A file input without a `name` sends its own files as `"file"`.
- Files go up in a multipart POST of their own to `/_domino/upload`, never through the WebSocket, and the event follows with a token per file; the handler gets the files themselves. A token only works for the page that uploaded it, only once, and expires after `{"domino": {"upload_ttl": 600}}` seconds. Files over 500 KB are spooled to temporary files, not held in memory, and every file is deleted once its event has been handled (or expired unclaimed): `save()` or copy what you want to keep.
- `{"domino": {"max_upload_mb": 16}}` (the default) limits each upload request, all its files together. A bigger one is refused with status 413 and the event isn't sent; the browser reports it like a failed event (the `domino:error` event, and the error overlay in debug mode).
- `filename`, `content_type` and `accept="image/*"` come from the browser and can't be trusted: check the content yourself, and use `werkzeug.utils.secure_filename` before putting a filename in a path. Handlers that use files are never predicted (see [Instant updates](#instant-updates)).
- Uploads can't be sent from other sites: `/_domino/upload` requires an `X-Domino-Page` header with a live page's id, which a form on another site can't add (and another site's script can't without a CORS preflight, which Domino never allows).
- After a successful submit, the form's file inputs are cleared like its other fields.

While its files go up, the element that fired (and its form) has `data-uploading` set to the percentage sent so far and the CSS variable `--domino-upload-progress`, from 0 to 1. `data-loading` and `aria-busy` are set as for any event, until the event's response arrives. A progress bar and a label, with CSS alone:

```python
css = {
	"form[data-uploading]::after": {
		"content": "''", "display": "block", "height": "6px", "background": "#2a7",
		"width": "calc(var(--domino-upload-progress) * 100%)",
	},
	"form[data-uploading]::before": {"content": "'Uploading ' attr(data-uploading) '%'"},
}
```

The latency simulator delays uploads too (a round trip of their own before the event's). See `examples/uploads/`.

### Server push

`component.refresh()` re-renders a component and sends it to every open page showing it, without waiting for a browser event. It can be called from anywhere, including a background thread. Mark components that will be refreshed with the class attribute `live = True`, so pages showing one listen for updates (see [How the browser talks to the server](#how-the-browser-talks-to-the-server)); pages without one don't. A component shown on several pages is rendered once per refresh. See `examples/clock/`.

### Reactive data

Like Meteor, Domino components re-render themselves when the data they show changes. Reading a `State` or querying a `Collection` inside `render()` subscribes the component; changing it re-renders every subscribed component on every open page and pushes the result (no `live = True` needed):

```python
from domino import Collection, State

messages = Collection("messages")   # shared by everyone
online = State(0)

class Chat(t.ul):

	def render(self):
		return [t.li() [m["text"]] for m in messages.find(sort=[("sent", -1)], limit=50)]

	def send(self, event):
		messages.insert({"text": event.form["text"], "sent": time.time()})  # every Chat updates
```

- `State(value)`: `.value` reads (and subscribes), `.value = x` changes it.
- `Collection(name)`: `insert(doc)` (returns the `_id`), `find(query, sort=..., limit=...)` (a cursor you iterate or `.fetch()`), `find_one`, `count`, `update(query, {"$set": ...}, multi=False)` and `remove(query)`, with MongoDB-style queries (`$gt`, `$in`, `$or`, dotted paths, ...). Documents come back as copies.
- Changes made while handling an event re-render each subscriber once, in the background, so the user who made the change gets their response straight away. Use `with batch():` to group changes made elsewhere, and `domino.wait()` in tests to let background updates finish.

See `examples/chat/`.

### MongoDB

Like Meteor, named collections live in MongoDB: `Collection("messages")` is the `messages` collection of the app's database, and `Collection()` without a name is an in-memory collection for this process only. Queries and updates use MongoDB's own syntax (all of it, not just the subset the in-memory collection supports). Documents get a string `_id` unless they have one.

The database comes from the `mongo.url` setting (e.g. `DOMINO_MONGO__URL=mongodb://db:27017/myapp?replicaSet=rs0`), with the database name taken from the URL (default `domino`); `MONGO_URL` works too, and `domino.mongo.connect(url)` sets it in code. When MongoDB runs as a replica set, a change stream per collection re-renders subscribers when *any* process changes the collection — another server process, a script, or `mongosh` — so it also works with several server processes. Without a replica set only this process's own writes update pages live.

## Forms

`domino.forms` builds a form from fields declared once. The browser checks them before anything is sent, the server checks them again on submit, errors appear next to each field, and your code gets typed values:

```python
from domino import forms

class Signup(forms.Form):

	name = forms.Text("Name", required=True, max_length=50)
	email = forms.Email("Email", required=True, live=True)
	age = forms.Integer("Age", min=13, max=120)
	plan = forms.Choice(["Hobby", "Pro", "Team"], default="Hobby")
	newsletter = forms.Checkbox("Send me news")
	password = forms.Password(required=True, min_length=8)
	confirm = forms.Password("Confirm password", required=True)

	submit_text = "Create account"

	def validate_email(self, email):                 # one field, on the server
		if users.find_one({"email": email}):
			return "That email is already registered."

	def validate(self, data):                        # across fields, once each is valid
		if data.password != data.confirm:
			raise forms.ValidationError("The passwords don't match.", field="confirm")

	def submitted(self, data):                       # only valid, typed data: data.age is an int or None
		users.insert({"name": data.name, "email": data.email, "age": data.age})
```

`Signup()` is a component that renders a `<form>`: a labelled input per field, in order, with its native constraints (`required`, `min`, `max`, `minlength`, `maxlength`, `pattern`, `type=email`), so the browser stops an invalid form without a round trip, and a submit button (busy while the submit is in flight, see [Loading and errors](#loading-and-errors)).

- **Fields**: `Text`, `TextArea`, `Email`, `Password`, `Integer`, `Float`, `Date`, `Checkbox` and `Choice(choices)`. Values are typed: `int`, `float`, `datetime.date`, `bool`, the choice itself (choices can be `(value, label)` pairs, so `Choice([(1, "Small"), (2, "Large")])` gives an `int`); an empty field is `None` (`""` for text, `False` for a checkbox). Every field takes a label (default: the name, capitalized), `required`, `default`, `help` (text under the input), `validators`, `live`, `messages` and any HTML attribute for the input (`autocomplete="email"`, `placeholder=...`). `Text` and its kinds take `min_length`, `max_length` and `pattern` (matched against the whole value); `Integer`, `Float` and `Date` take `min` and `max`.
- **On submit** the server checks every field, whatever the browser did. With errors, each is shown under its field (`aria-invalid` and `aria-describedby` on the input, the message in a `role="alert"` element) and the form keeps what the user typed, except passwords, which aren't sent back to the page (`Password(keep=True)` changes that). Without errors `submitted(self, data)` is called with a `forms.Data` (a dict you can also read as `data.age`) and the form is reset to its initial values. In `submitted()`, `self.error("email", "Already taken")` rejects the submit after all: the error is shown and the values stay. `self.error(None, message)` shows a message above the form, and `self.reset()` clears it.
- **Custom checks**: `validators=[fn]` and `validate_<field>(self, value)` get the typed value of a field that isn't empty; `validate(self, data)` gets all of them once every field is valid. Any of them can return a message, raise `forms.ValidationError(message)` (with `field=` in `validate`) or call `self.error(...)`. Messages of the built-in checks can be changed per field: `forms.Text(required=True, messages={"required": "Who are you?"})`.
- **Live validation**: `live=True` checks a field on the server when its value changes (on leaving a text field), `live="blur"` whenever the user leaves it, and `live="input"` while they type, after `debounce=` ms (300 by default). It runs that field's checks only, through a normal event, and leaves the others alone.
- **Options**: `Signup(initial={"plan": "Pro"})` fills fields in (typed values, also what the form resets to), `Signup(submitted=callback)` hands the data to someone else (a parent showing a success view, say), and `Signup(submit_text="Join")` or the class attribute `submit_text` sets the button's text.
- **Layout**: fields are `<div class="field">` blocks, styled plainly by `Form`'s class-level `css` (scoped to `.Form`, so your own component's `css` or the page's styles win; `--form-accent` and `--form-error` set the colors). To lay a form out yourself, override `render()` and use `self.fields`: `self.fields.email.label()`, `.input(**attributes)`, `.help()`, `.error()`, or `.render()` for the whole block; `for field in self.fields` goes through them in order. The submit event stays bound whatever `render()` returns.
- **Without the component**: `Signup.validate_data(event.form)` returns `(data, errors)`, typed data and a dict of messages by field name, for any handler or route (`request.form` works too).

Field names can't be names a form already uses (`errors`, `fields`, `error`, `reset`, `render`, `id`, ...); declaring one raises an error. See `examples/forms/`.

## Accounts

`domino.accounts` adds sign-up, login and logout, like Meteor's accounts packages. Users are documents in the `users` collection (MongoDB):

```python
from domino import accounts

@app.route("/")
def index():
	return Document() [accounts.UserMenu()]        # "Signed in as …" + Log out, or Log in / Sign up links

@app.route("/login")
def login():
	return Document() [accounts.LoginForm()]       # also SignupForm(), LogoutButton(), OAuthButton("github"),
	                                               # ForgotPasswordForm(), ChangePasswordForm(), ... (below)

@app.route("/private")
@accounts.login_required                           # under @app.route, or on a page's page()
def private():
	user = accounts.current_user()
	return Document() [t.p() [f"Hello {user['email']}"]]
```

- `accounts.current_user()` is the signed-in user's document (without its password hash), or None; `accounts.user_id()` is just the id. Both are reactive: a component that reads them in `render()` re-renders when the user logs in or out on that page.
- `accounts.create_user(email, password, name=None)`, `accounts.login(email, password)` and `accounts.logout()` can be called from your own event handlers. Bad input raises `accounts.AccountError`, whose message is meant for the user (a wrong email and a wrong password both give "Wrong email or password"). Passwords need at least 8 characters and are hashed with werkzeug's `generate_password_hash`; emails are stored lowercased and must be unique (a unique index is created in MongoDB).
- The forms show errors inline, keep the typed email, and after logging in go to `?next=` if the page has one (only paths on this site are followed). `login_required` sends visitors who aren't signed in to the `accounts.login_url` setting (default `/login`) with `?next=` set to the page they asked for.
- After 5 failed logins for an email within a minute, it's locked until that minute has passed; one IP address gets 20. Change these with the `accounts.max_attempts` and `accounts.lockout_seconds` settings. The counts are kept in the server process's memory, so each process (and a restart) counts on its own. Behind a proxy, every client shares the proxy's address unless you set up Werkzeug's `ProxyFix`.
- `domino.redirect(url)` in any event handler sends the browser to `url` when the response arrives. It only accepts paths on this site (`/notes`, not `//evil.com` or `https://...`); outside event handlers it's Flask's `redirect()`.
- The forms are [`domino.forms`](#forms) forms (`LoginForm`, `SignupForm` and the ones below), so they're laid out and styled like any other, and can be subclassed to change labels, messages or `submit_text`.

### Password reset, email verification and changing the password

These send email, so set up [Email](#email) first (in debug mode emails are printed in the terminal, links included). Put each component on a page of its own, like the login page:

```python
# pages/forgot-password.py
def page():
	return accounts.ForgotPasswordForm()          # email -> "If an account exists for that email, we've emailed a link ..."

# pages/reset-password.py                        # the emailed link: /reset-password?token=...
def page():
	return accounts.ResetPasswordForm()           # new password + confirmation

# pages/verify-email.py                          # the link emailed after signing up
def page():
	return accounts.VerifyEmail()

# pages/check-email.py                           # "check your email", with a button to send the link again
def page():
	return accounts.CheckEmail()

# pages/members.py
@accounts.login_required(verified=True)          # unverified users go to /check-email?next=...
def page():
	...

# pages/settings.py
@accounts.login_required
def page():
	return accounts.ChangePasswordForm()          # current password + new password + confirmation
```

- **Forgot your password?** `ForgotPasswordForm` gives the same answer whether or not an account has that email, so it can't be used to find out who has one (emails go out in the background, so it doesn't take longer either). The email links to the `accounts.reset_url` page (default `/reset-password`) with a token that expires after `accounts.reset_link_seconds` (default 3600) and works once: it's bound to the user's current password hash, so it stops working as soon as the password is reset or changed. Resetting also marks the email verified (the link proved it's theirs) and ends a login lockout. With the `accounts.forgot_url` setting (e.g. `/forgot-password`), `LoginForm` shows a "Forgot your password?" link to it.
- **Email verification.** With `{"accounts": {"verify_email": true}}` (off by default), `SignupForm` emails new users a link to the `accounts.verify_url` page (default `/verify-email`), valid for `accounts.verify_link_seconds` (default 3 days). `current_user()["verified"]` says whether they've opened it; users who signed in with GitHub or Google with a verified email are verified already. `@accounts.login_required(verified=True)` sends unverified users to the `accounts.check_email_url` page (default `/check-email`), whose button sends the link again. Your own code can call `accounts.send_verification_email(user)`, `accounts.send_reset_email(user)`, `accounts.verify_email(token)`, `accounts.reset_password(token, password)` and `accounts.set_password(user_id, password)`.
- **Changing the password.** `ChangePasswordForm` asks for the current password; wrong guesses count as failed logins for that email, so they're locked out the same way. Other browsers signed in to the account stay signed in: sessions live in cookies, so there's no server-side list of them to end ("log out other sessions" isn't possible). Reset links sent before stop working.
- **Rate limits.** Reset emails are limited per address (whether or not it has an account) and verification emails per user: `accounts.max_emails` (default 3) in `accounts.email_window_seconds` (default 900), and four times as many per IP address. Like the login lockout, the counts are kept in each server process's memory.
- **Links** in emails are built on the `public_url` setting (`{"public_url": "https://example.com"}`), or else on the address the request came to. Set it in production: otherwise a request with a forged `Host` header could get a reset link to another site emailed to a user (a warning is logged once outside debug mode). Tokens are signed with the `secret_key` and a salt per purpose, so a verification token can't be used as a reset token, and changing the secret key invalidates them all.

**Sessions.** The signed-in user's id is kept in Flask's signed session cookie, which needs the `secret_key` setting: put a long random string in `settings.local.json` or `DOMINO_SECRET_KEY`. In debug mode an app without one gets a random key per process, with a warning, so logins don't survive a restart; outside debug mode accounts refuse to work without it. Domino pages outlive their request (events and pushes from other users' changes run later), so each page remembers who was signed in when it was loaded, and login and logout update the page as well as the cookie. Other open tabs of the same browser notice on their next page load, not live. Logging in starts a fresh session (nothing from the old cookie is kept) and lasts 31 days (Flask's `PERMANENT_SESSION_LIFETIME`); logging out clears the cookie in that browser. Since the session lives in the cookie, there's no server-side list of sessions to revoke.

**Cookies.** Domino apps send the session cookie with `HttpOnly` (Flask's default), `SameSite=Lax`, and, outside debug mode, `Secure`, so in production it's only sent over HTTPS. For an HTTP-only deployment set `{"domino": {"secure_cookies": false}}`.

**Events and CSRF.** The event endpoint accepts only `application/json` requests (anything else gets 415). A form on another site can't send JSON, and another site's script can't send it without a CORS preflight, which Domino never allows, so a malicious page can't fire events with the user's cookie. Events also need the page's random id, which only the page itself has.

**Keep the users collection on the server.** Domino has no client-side database: the browser only sees what components render. Render fields you choose (`user["name"]`), never whole user documents, and don't build components that list `accounts.users` for everyone. `current_user()` leaves out the password hash, but `accounts.users.find()` doesn't.

### GitHub and Google

Add a provider's OAuth app credentials to the settings, for example in `settings.local.json`:

```json
{"accounts": {"github": {"client_id": "...", "client_secret": "..."}, "google": {"client_id": "...", "client_secret": "..."}}}
```

The callback URL to register with the provider is `https://<your site>/_domino/accounts/github/callback` (or `google`). `LoginForm` and `SignupForm` then show a "Continue with GitHub" link, and `OAuthButton("github")` adds one anywhere; providers that aren't configured render nothing. Signing in uses the authorization-code flow with a random `state` kept in the session, so a callback this browser didn't start is refused. The user is found by their provider account id, or else linked to an existing user with the same email if the provider says it's verified, or else created; an unverified email never links to an existing account. Provider details are kept in `user["services"]["github"]`; access tokens aren't stored.

See `examples/accounts/`.

## Email

`domino.mail.send(to, subject, text, html=None)` sends an email (`to` is an address or a list of them). Set up SMTP in the settings, with the password in `settings.local.json` or the environment (`DOMINO_MAIL__PASSWORD`):

```json
{"mail": {"backend": "smtp", "host": "smtp.example.com", "port": 587, "tls": true, "username": "apikey", "from": "My App <noreply@example.com>"}}
```

- `"tls": true` uses STARTTLS (port 587 by default), `"ssl": true` a TLS connection from the start (port 465); `timeout` is in seconds (default 10).
- SMTP emails are sent by a background thread, so `send()` returns at once: event handlers don't wait seconds for a mail server, and a page doesn't answer slower when an email goes out. A failed delivery is logged, not raised, and emails still queued when the process exits get a few seconds to go out.
- The `"console"` backend prints each email to the server's output instead (links on lines of their own, so terminals make them clickable); it's the default in debug mode. The `"memory"` backend keeps them in `domino.mail.outbox`.
- In tests the memory backend is always used, whatever the settings, so tests never send real email. The `mail_outbox` fixture gives the emails sent during the test (each has `.to`, `.subject`, `.text`, `.html` and `.links`):

```python
# pages/forgot-password_test.py
from domino import accounts

def test_reset_email(page, mail_outbox):
	accounts.create_user("ada@example.com", "correct horse")
	page.fill("input[name=email]", "ada@example.com")
	page.click("button", text="Email me a link")
	assert mail_outbox[0].subject == "Reset your password"
```

- Outside debug mode and tests, sending without a backend raises `domino.mail.MailConfigError`.

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
    "domino": {"page_ttl": 600, "max_pages": 500, "keepalive": 15, "websocket": true, "workers": 32, "navigation": true},
    "public": {"greeting": "Hello"}
}
```

- `domino` sets Domino's Flask config: `page_ttl` becomes `app.config["DOMINO_PAGE_TTL"]`, and so on. Changes to `app.config` made in code afterwards still win. From the environment, these are `DOMINO_DOMINO__PAGE_TTL=600` and so on.
- `secret_key` sets `app.secret_key`.
- `public` is sent to the browser, where it's available as `Domino.settings` (like `Meteor.settings.public`). `Document` adds it to the page head; pages built without `Document` can add `PublicSettings()` from `domino.components` to theirs. Nothing outside `public` is sent.

See `examples/settings/`.

### Instant updates

Handlers that only change their component's own `State` with plain expressions — `self.count += 1`, `self.open = not self.open`, `if len(self.items) < 3: ...` — feel instant even on a slow connection, with nothing to configure. So do lambdas that only call such a method with plain values, like `on_click=lambda event, index=index: self.select(index)` (the method's parameters can be read like constants). Domino decides which handlers qualify by reading their code: anything that calls functions (like `messages.insert(...)`), uses the event's value, or touches anything but the component's `State` is never run ahead of time.

When the server renders such a component it follows those handlers from its current state to every state they lead to, renders each state once, and ships them inside the component (inert JSON) with which event leads to which state. Menus, tabs, accordions, toggles, a stepper with bounds or a carousel have only a few states, so the browser can show any number of clicks in a row the moment they happen, without waiting for the server even once. The events still go to the server, in order, and the server stays the source of truth: its answer to the last click in flight confirms what's shown, or puts it right if something changed on the server meanwhile (answers to earlier clicks don't undo later ones). If an event fails, the component goes back to what the server last showed. While the page shows something the server hasn't confirmed, the component has a `data-predicted` attribute.

A component whose states could go on forever (a counter) gets the states one click away instead, as do those with more than 16 states or more than 32 KB of HTML for them; set `optimistic_states = n` on the class to change the number. Set `optimistic = False` to turn it all off (each state costs a render on the server). See `examples/instant/`.

```python
class Tabs(t.div):

	active = State(0)

	def render(self):
		return [
			t.button(on_click=lambda event, index=index: self.select(index)) [name]
			for index, name in enumerate(["Overview", "How", "Truth"])
		] + [t.p() [f"Tab {self.active}"]]

	def select(self, index):
		self.active = index
```

### Experimental: client components

A component with `client = True` runs in the browser, in Python: the server renders its first HTML, then MicroPython compiled to WebAssembly (about 190 KB, loaded only on pages that need it) takes over, so its handlers, re-renders and `after()` timers never wait for the server and keep working offline. The API is the same (`State`, `render()`, `on_click=`, class-level `css`), and `self.emit("save", value)` runs a handler the server component around it passed in (`Sketch(on_save=self.save)`).

```python
class Counter(t.div):

	client = True
	count = State(0)

	def render(self):
		return [t.button(on_click=self.increment) [f"Clicked {self.count} times"]]

	def increment(self):
		self.count += 1
```

**The component's whole module is sent to the browser and is public**: it may only import `domino.tags`, `State` and `math`, `random`, `time`, `json` (anything else, like a `Collection` or your server modules, stops the app at startup), and must never hold server-only code or secrets. The runtime comes from jsDelivr, or while debugging from a copy downloaded once into `~/.domino/client-runtime` (`{"domino": {"client_runtime": "local" | "cdn" | "<url>/", "client_python": "micropython" | "pyodide"}}`). It's a prototype: see [docs/research/client-python.md](docs/research/client-python.md) for what works, measurements, limitations and open problems, and `examples/client/`.

### Simulating a slow connection

Locally every click feels instant. To feel the app the way users on a slow connection will, run `Domino.enableLatencySim(300)` in the browser console: each round trip to the server then takes 300 ms (pushes are delayed too), for that tab, until `Domino.disableLatencySim()`. Or set it for the whole app while debugging with `{"domino": {"latency": 300}}` in `settings.json`; it's ignored when the app isn't in debug mode.

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

Find elements with simple CSS selectors (`tag`, `.class`, `#id`, `[attr=value]`, and descendants like `form input`), optionally narrowed with `text=`. Pages can be driven with `click`, `fill` (set a value without firing events), `type` (fires `input`), `select`, `check`, `submit`, and `upload` (picks files in a file input and fires its `change`; each file a path or `(filename, bytes[, content_type])`, e.g. `page.upload("input[name=photo]", ("me.png", data))`; they're uploaded with that event and with the form's submit, as in a browser). Inspect them with `text`, `value`, `find`/`find_all`, `html`, `status` and `path`. `sync()` applies changes other pages pushed to this one, `run_timers()` fires pending `after()` timers right away, and `load(path)` navigates (redirects are followed and cookies kept, like a browser, so a login carries over). A failing handler, or a selector that matches nothing, fails the test with the traceback and the page's text.

Outside `pages/`, `app.test_page(path)` gives the same simulated browser for any app. See the examples' `pages/*_test.py`, e.g. [examples/counter/pages/index_test.py](examples/counter/pages/index_test.py), [examples/chat/pages/index_test.py](examples/chat/pages/index_test.py) (two windows) and [examples/accounts/pages/private_test.py](examples/accounts/pages/private_test.py) (signing up and logging out).

### MongoDB in tests

Like `meteor test`, pages with named Collections can be tested with nothing to set up. The first time a test that uses `page` or `open_page` connects to MongoDB, a `mongod` is started for the test session (the same cached download as `domino run`'s, on a free port, with its data in a temporary folder, so your development database in `.domino/` is never touched), and it's stopped when the session ends. Tests that don't use named Collections never start it.

- Each test gets an empty database of its own (`domino_test_<session>_<n>`), dropped in the background after the test. Collections switch to it by themselves, and change streams follow, so changes from one test never reach the next. `sync()` waits for the change stream to announce this process's writes, so a second tab sees them straight away. The overhead is about a millisecond per test.
- The `domino_db` fixture gives the same database (as a pymongo `Database`) to any test, including tests that use collections directly: `def test_import(domino_db): ...`.
- To use a server you run instead (e.g. in CI), set `DOMINO_TEST_MONGO_URL=mongodb://127.0.0.1:27017/?replicaSet=rs0`; nothing is started then. A `mongo.url` setting (or `DOMINO_MONGO__URL`) is used the same way. Either way, tests only create and drop their own databases on it, never the one the URL names. Use a replica set, so pages update live.
- To turn it off, pass `pytest --no-mongo`, set `DOMINO_NO_MONGO=1`, or set `{"mongo": {"auto": false}}`. A test that uses a named Collection then fails with a message saying so. If `mongod` can't be downloaded or started (offline, say), tests that need it fail with the reason and a pointer to `DOMINO_TEST_MONGO_URL`.
- With pytest-xdist, each worker starts its own `mongod`, or shares the `DOMINO_TEST_MONGO_URL` server with databases of its own.

## How the browser talks to the server

Served through `app.asgi` (with uvicorn, which `app.run()` and `domino run` use), each tab opens **one WebSocket** at `/_domino/ws`. Events go up it and their results come back down, and so do updates pushed by `refresh()` or reactive data, so there's no request per event and no stream per tab. An idle tab costs the server a few KB and no thread.

- Event handlers are still plain (sync) Python. They run in a pool of worker threads (`{"domino": {"workers": 32}}`, the default), so a slow handler never holds up other tabs. A tab's events run one at a time, in the order they were sent, under the page's lock, exactly as over HTTP.
- Handlers get a request context made from the WebSocket's handshake: `request.cookies`, `session` and `url_for` work. A socket can't set cookies, so when a handler changes the session (logging in, say), the result carries a one-time token that the page exchanges for the new cookie with a quick same-origin POST before it goes on. The socket's later events see the new session too.
- The handshake is refused when its `Origin` isn't this site, so other sites can't open a socket with your visitors' cookies.
- Moving to another page of the app (see [Moving between pages](#moving-between-pages)) keeps the socket: it's moved over to the new page, which also brings the cookies the browser had when it loaded that page. Over HTTP, the Server-Sent Events stream is reopened for the new page if it needs one.
- An open socket keeps its page alive. If the page is gone (expired, or the server restarted), a page showing a live component reloads; others reload on their next event, as over HTTP.
- Where the socket can't connect or keeps dropping (some proxies block WebSockets), the page falls back by itself after a few tries to POSTing each event to `/_domino/events` and, if it shows a live component, Server-Sent Events from `/_domino/stream`. That's also what pages use when the app is served as plain WSGI (`gunicorn app:app`, `flask run`), which keeps working as before. A tab sends its POSTs one at a time, so the server handles its events in the order they fired, as over the socket.
- `{"domino": {"websocket": false}}` turns the socket off; pages then always use HTTP and Server-Sent Events.
- **Patches.** Over the socket, a re-rendered component is usually sent as what changed since the last HTML the socket sent for it, not all of it: components render one element per line, so a change is a few lines, and a moved or shifted block is copied rather than sent again. Appending a message to a chat of 200 goes from 28 KB to about 200 bytes, a changed cell of a 500-row table from 200 KB to under 200 bytes. The server keeps the last HTML it sent per component (up to 512 KB per socket, least recently sent dropped first; a `refresh()` shared by many pages keeps one copy for all of them) and the browser keeps the same, so either side can tell if they disagree, in which case the browser asks for the whole HTML again. Small components (under 1 KB) and changes that touch most of a component are sent whole, as are POST responses and Server-Sent Events. Large predicted states (see [Instant updates](#instant-updates)) are sent as patches against one of them. `{"domino": {"patches": false}}` turns them off.
- **Hidden tabs pause.** When a tab is hidden (another tab is in front, the window is minimized), it tells the server, which then stops rendering for it: reactive changes and `refresh()` only note which of its components changed. When it's shown again, each of those is rendered once and sent, however often it changed meanwhile. An event from a hidden tab catches it up first. 100 hidden tabs on a busy chat cost the server next to nothing instead of a render each per message. (Pages on Server-Sent Events aren't paused.)
- **Compression.** uvicorn compresses each WebSocket message (per-message deflate), which costs about 40 KB of memory per open socket. With patches most messages are a few hundred bytes, but compression still shrinks them several times over, and whole components (page switches, first updates) many times, so it's on by default. For a server holding many thousands of mostly idle tabs, `{"domino": {"ws_compression": false}}` saves that memory (`app.run()`, `domino run` and `domino serve` pass it to uvicorn; with `uvicorn` itself, use `--ws-per-message-deflate false`).

## Deploying

Like `meteor deploy`, one command gets an app online, but onto a platform you choose, from files you can read and keep:

```
domino deploy fly        # Fly.io: does everything, with Fly's flyctl command
domino deploy render     # Render: writes a Blueprint you create from Render's dashboard
domino deploy docker     # a Docker image, to run anywhere
```

Each takes the app's folder (default: the current one). Every one of them first runs `domino build`, which writes into the app's folder:

- `Dockerfile`: Python 3.12 (slim), the app's `requirements.txt` installed with `domino-web` pinned to the version you're running, the app run by a user without root rights, `domino serve` on port 8000, and a health check.
- `.dockerignore`, which keeps `.domino/`, `settings.local.json`, `.env`, `.git`, virtualenvs and caches out of the image.
- `requirements.txt`, if the app has none: just `domino-web==<version>`. Add the app's other dependencies to it.

Files that are already there are kept (`--force` writes them again, except `requirements.txt`, which is always yours), so you can edit them. Commit them with the app. The app serves `GET /_domino/health` (it answers `ok` without making a page), which the platforms use to check it's up. The number of worker processes is one per CPU core, or `WEB_CONCURRENCY` if it's set.

**Fly.io.** `domino deploy fly` writes `fly.toml` (port 8000, HTTPS only, health checks on `/_domino/health`, one shared CPU with 512MB; the app gets the folder's name with a random ending, or `--name`). If `flyctl` is installed ([install it](https://fly.io/docs/flyctl/install/)), it then logs you in if needed, creates the app the first time (`fly launch --no-deploy --copy-config`), sets the app's secrets with `fly secrets set`, and runs `fly deploy`. The app ends up at `https://<name>.fly.dev/`. Without `flyctl`, it prints these commands to run yourself. Run it again to deploy a new version.

**Render.** `domino deploy render` writes `render.yaml`, a [Blueprint](https://render.com/docs/blueprint-spec): a Docker web service with its health check, a generated `DOMINO_SECRET_KEY` and a `DOMINO_MONGO__URL` for you to fill in. Render creates services from Blueprints in its dashboard, not from your computer, so then: push the repository to GitHub (or GitLab or Bitbucket), choose **New > Blueprint** in the Render dashboard, pick the repository, and enter your MongoDB URL when asked. Later pushes deploy by themselves. For an app in a subfolder of its repository, the paths in `render.yaml` are set for that, and you point Render at the subfolder's `render.yaml`.

**Docker.** `domino deploy docker` builds the image (if Docker is running) and prints the `docker run` command, with the environment variables it needs. It also writes `docker-compose.yml`, which runs the app together with a MongoDB of its own (a single-node replica set, its data in a Docker volume): `export DOMINO_SECRET_KEY=...` and then `docker compose up -d` serves it on http://localhost:8000. Any host that runs containers can run the image.

**MongoDB.** Named collections (`Collection("tasks")`) need a MongoDB in production, and it must be a replica set, since live updates come from its change streams. [MongoDB Atlas](https://www.mongodb.com/cloud/atlas) clusters are, including the free one: copy its connection string (`mongodb+srv://...`) and give it to `domino deploy` with `--mongo-url`, or have it in `DOMINO_MONGO__URL` (or `MONGO_URL`), or in `settings.local.json` as `mongo.url`. `domino deploy fly` asks for it when it finds none, and passes it to Fly as a secret. `domino deploy` warns when the app's code uses named collections (it looks for `Collection("` in its `.py` files) and no MongoDB URL is set. The development MongoDB's URL (`127.0.0.1`) is never used for production.

**The secret key.** Logins and sessions need a `secret_key`. `domino deploy fly` makes a random one and sets it as the Fly secret `DOMINO_SECRET_KEY` the first time (later deploys keep it, so nobody is signed out; one in your `DOMINO_SECRET_KEY` environment variable is used instead if set), and Render generates one. Secrets are only passed to the platform's commands or printed, never written into the app's files. Keep `secret_key` out of `settings.json`, which is committed with your code; `domino deploy` warns when it's there.

**One instance.** A page lives in the memory of the server process that made it, so an app runs on one machine (with a worker process per CPU): `domino deploy fly` deploys a single machine (`--ha=false`), and Render's service has one instance. Choose a bigger machine to serve more. The session cookie is only sent over HTTPS (Fly and Render serve HTTPS); to try an image over plain `http://localhost`, add `-e DOMINO_DOMINO__SECURE_COOKIES=false` (`docker-compose.yml` sets it).

### Serving in production

`domino serve` is what the Dockerfile runs, and works on any server:

```
domino serve myapp --host 0.0.0.0 --port 8000
```

It uses every CPU core, with nothing to set up. It starts one worker process per core (`--workers N` to choose), each with its own copy of the app, and listens on the port itself, passing each request to a worker. It's for production, so it doesn't reload on changes or start a development MongoDB: set `mongo.url` (e.g. `DOMINO_MONGO__URL`). An app using Tailwind gets its minified CSS built first (run `domino tailwind build` when building an image; see [Tailwind in production](#tailwind-in-production)).

A page lives in the memory of the worker that rendered it: its components, their state and their event handlers. So a tab's events must reach that worker, and they do, without sticky sessions or anything else to configure: each page id starts with its worker's number (`w3-...`), and `domino serve` sends every request about a page to the worker the id names. New page loads go to the least busy worker. The same goes for the token a login over the WebSocket hands the browser.

- If a worker crashes, it's started again. Its pages are gone, so their tabs reload, as after a restart. Ctrl+C or `SIGTERM` stops the workers, letting them finish what they're doing; if `domino serve` itself is killed, its workers stop too.
- Named collections (`Collection("messages")`, MongoDB) are shared: a change made in any worker re-renders the components showing it in every worker, through MongoDB's change streams (which need a replica set).
- Everything else in Python memory is per worker: `Collection()` without a name, module-level `State`, caches, the failed-login counts. Two tabs on different workers don't see each other's in-memory data, so keep what users share in MongoDB.
- A background thread the app starts (like `examples/clock/`'s) runs in each worker, and its `refresh()` updates that worker's pages.
- Workers load the app side by side, so starting takes about as long as with one.

`domino serve --workers 1` serves one process with no router, as does uvicorn itself: `uvicorn app:app.asgi --host 0.0.0.0 --port 8000`. `app.run(workers=4)` (without debug mode) is the same as `domino serve --workers 4`, for an app defined at the top level of its file.

Behind a proxy such as nginx (for HTTPS, say), let it pass WebSockets for `/_domino/ws` (with nginx: `proxy_http_version 1.1` and the `Upgrade`/`Connection` headers). Workers see the visitor's address in `request.remote_addr`; as with uvicorn, an `X-Forwarded-For` header is believed only from the addresses in `FORWARDED_ALLOW_IPS` (default `127.0.0.1`). Plain WSGI servers (`gunicorn app:app`) work too, with the HTTP fallback above, but then each tab showing a live component holds a server thread, and several worker processes need sticky sessions.

Each page load gets its own state, which expires after `DOMINO_PAGE_TTL` seconds of inactivity (default 1800). At most `DOMINO_MAX_PAGES` pages are kept per worker (default 1000); when a page has expired, the browser reloads it. To change how pages are kept, subclass `domino.PageStore` (or `MemoryPageStore`) and pass `Domino(__name__, page_store=...)`.

## Tests

```
pip install -e .[test]
python -m pytest
```

Tests marked `mongo` are skipped unless `DOMINO_TEST_MONGO_URL` points at a MongoDB replica set, e.g. `DOMINO_TEST_MONGO_URL="mongodb://127.0.0.1:27017/?replicaSet=rs0" python -m pytest`. The examples' page tests use it too, or else start a `mongod` themselves (see [MongoDB in tests](#mongodb-in-tests)).

## Releasing

Bump `version` in `setup.py`, then publish a GitHub Release (e.g. tag `v0.1.0`). The `Publish to PyPI` workflow builds the package and uploads it to PyPI as `domino-web`.
