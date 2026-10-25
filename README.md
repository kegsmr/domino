# Domino

An experimental Python web framework built on Flask. It currently resembles a glorified HTML/CSS generator, but more features are planned.

**This project is a work-in-progress! Not all features are functional yet.**

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

Pages are on when the app's folder (the folder of the module passed to `Domino(__name__)`) has a `pages/` folder. `Domino(__name__, pages="views")` uses another folder and `pages=False` turns them off. `@app.route` keeps working alongside pages; a route for a URL a page already serves is an error, naming both, when the app starts. Pages are found once, when the app is created, and each file is imported once; while debugging, the reloader restarts the server when one changes. Pages render exactly like `@app.route` views, with events, reactive data and server push.

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

`domino create <name>` makes a folder with a small reactive app: a tiny `app.py`, `pages/index.py` and `pages/layout.py`, a component in `components/`, a `Collection` in `data.py`, a test for the page in `pages/index_test.py` (run it with `pytest`; see [Testing your app](#testing-your-app)), a `settings.json` with a `public` block, and a `.gitignore`. It won't write into a folder that isn't empty.

`domino run [folder or app.py] [--port 5000] [--host 127.0.0.1] [--no-mongo] [--mongo-version 7.0]` runs the app (default: the current folder) in debug mode with uvicorn's reloader, so it restarts when you save a `.py` file in the app's folder. For a folder it runs its `app.py`; a folder with only `pages/` (and maybe `settings.json`) needs no `app.py` at all, as `domino run` makes the app itself. `domino --version` prints the version.

`app.run(debug=True)` (what `python app.py` does in the examples) serves the same way. Reloading starts a new process that loads the app again from its file, so the app must be assigned at the top level of the module (`app = Domino(__name__)`); otherwise it runs without reloading. Without debug mode, `app.run()` serves with uvicorn without reloading.

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

## Templates

Besides tag classes, components can be written as HTML, in two ways. See `examples/templating/`.

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

A component without a `render()` whose module has a template next to it named after the class (`TodoList` → `todo_list.html`) or after the module (`counter.py` → `counter.html`) renders that template. Its `State` values and methods are available by name, and the component itself as `this` (Jinja keeps `self` for its blocks). `on(click=handler)` binds events, like `on_click=`; it takes several events and `debounce=`. Reading `State` subscribes the component and its handlers are predicted for instant updates, as with `render()`. A `render()` method, when there is one, wins over the template.

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

Use template strings for interactive components written in Python, Jinja for pages, layouts and markup-heavy parts, with components dropped in where they need to be live.

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

If a callback raises, the server logs the exception and answers with status 500. In production the response only says `"Internal Server Error"`; with `app.debug` on it includes the exception and its traceback, and the browser shows them in an overlay. Either way the browser dispatches a cancelable `domino:error` event on the element that fired, which bubbles to the document, with `detail` holding `error`, `traceback` (debug only) and `eventId`. Cancel it to handle errors yourself:

```js
document.addEventListener('domino:error', (e) => {
    e.preventDefault();  // no overlay or console.error
    showToast('Something went wrong');
});
```

See `examples/loading/`.

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
	return Document() [accounts.LoginForm()]       # also SignupForm(), LogoutButton(), OAuthButton("github")

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

See `examples/accounts.py`.

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

## Deployment

Serve the ASGI app with uvicorn (installed with Domino):

```
uvicorn app:app.asgi --host 0.0.0.0 --port 8000
```

Behind a proxy, let it pass WebSockets for `/_domino/ws` (with nginx: `proxy_http_version 1.1` and the `Upgrade`/`Connection` headers). Plain WSGI servers (`gunicorn app:app`) work too, with the HTTP fallback above, but then each tab showing a live component holds a server thread.

Components and their event handlers live in the memory of the server process that rendered the page. Each page load gets its own state, which expires after `DOMINO_PAGE_TTL` seconds of inactivity (default 1800). At most `DOMINO_MAX_PAGES` pages are kept (default 1000); when a page has expired, the browser reloads it.

Because of that, run a single process, or use sticky sessions so a browser keeps talking to the same worker. To change how pages are kept, subclass `domino.PageStore` (or `MemoryPageStore`) and pass `Domino(__name__, page_store=...)`. A store shared between processes would need to serialize components and their callbacks.

## Tests

```
pip install -e .[test]
python -m pytest
```

Tests marked `mongo` are skipped unless `DOMINO_TEST_MONGO_URL` points at a MongoDB replica set, e.g. `DOMINO_TEST_MONGO_URL="mongodb://127.0.0.1:27017/?replicaSet=rs0" python -m pytest`. The examples' page tests use it too, or else start a `mongod` themselves (see [MongoDB in tests](#mongodb-in-tests)).

## Releasing

Bump `version` in `setup.py`, then publish a GitHub Release (e.g. tag `v0.1.0`). The `Publish to PyPI` workflow builds the package and uploads it to PyPI as `domino-web`.
