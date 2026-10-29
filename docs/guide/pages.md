# Pages & navigation

File-based routing, layouts, and page switches without reloading.

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
    404.py               the page for URLs no page serves
    _helpers.py          not a page: names starting with _ are private
  layouts/
    main.html            <layout name="Main">: the document pages go in
  components/            components the pages use
  data.py                Collections the pages import
  settings.json
```

A page file defines `page()`, returning anything a route can: a component, a `Document`, a string or a Flask response. The parts of the URL in brackets arrive as keyword arguments. `[int:id].py` uses Flask's `int` converter (`float`, `uuid` and `path` work too; on Windows, where file names can't have colons, write `[id=int].py`), and `[...path].py` matches the rest of the URL, slashes included (at least one segment: `/docs` itself needs `docs/index.py`).

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

A layout is the document and navigation pages share. It's a file of its own, by convention in `layouts/`: `<layout name="Main">` around a whole `<html>` document, with `<slot />` where the page goes. A page names its layout, and its other attributes are the layout's values:

```html
<!-- layouts/main.html -->
<layout name="Main">
    <html lang="en">
        <head>
            <title>{{ title }} · My site</title>
        </head>
        <body>
            <nav>
                <a href="/">Home</a>
                <a href="/about">About</a>
            </nav>
            <main><slot /></main>
        </body>
    </html>
</layout>
```

```html
<!-- pages/about.html -->
<page layout="Main" title="About">
    <h1>About</h1>
    <p>...</p>
</page>
```

- A page in a layout is the whole document: Domino adds the doctype, its script and the components' CSS. `<page>` without `layout=` is just its markup (or a whole document of its own, with `<html>`).
- A layout needs no Python class. What a page gives it (`title="About"`) are its values, and a value it isn't given shows nothing. A class with the layout's name (`layouts/main.py`, `class Main(t.div)`) adds what any component has: helpers (the signed-in user for the nav), `State` and handlers (a menu that opens), live data. Its handlers are answered by the server rather than predicted.
- Layouts nest: `<layout name="Admin" layout="Main">` goes inside Main (given the same values), so `<page layout="Admin">` gets the site's document with an admin frame around the page.
- From Python, a page returns it like any component: `return Main(title="About") [Article()]`.
- Links between pages keep the layout's elements as they are (see [Moving between pages](#moving-between-pages)), and saving it updates open pages.
- `pages/layout.html` (which wrapped a folder's pages automatically in development versions) stops the app with a message saying how to move it.

The older way still works: a `layout.py` in `pages/` or a subfolder wraps every page in its folder and below. It defines `layout(content)` and returns the page wrapped in whatever every page shares, usually a `Document` with the navigation. Layouts nest from the `pages/` folder inward, and one that names URL parameters (`layout(content, id)`) receives them.

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

Pages are on when the app's folder (the folder of the module passed to `Domino(__name__)`) has a `pages/` folder. `Domino(__name__, pages="views")` uses another folder and `pages=False` turns them off. `@app.route` keeps working alongside pages; a route for a URL a page already serves is an error, naming both, when the app starts. Pages are found once, when the app is created, and each file is imported once; while debugging, [hot reloading](cli.md#hot-reloading) swaps in pages that change and adds or removes the routes of pages added or deleted. Pages render exactly like `@app.route` views, with events, reactive data and server push.

## Moving between pages

Clicking a link to another page of the app swaps that page in without reloading, like a single-page app, with nothing to write: Domino fetches the page as usual (a normal GET, marked with an `X-Domino-Navigate: 1` header), morphs the document into it, keeping the nodes that stay the same (the layout's navigation, say), and adds the URL to the history, so back and forward work too. The title, `<head>` styles and component CSS follow the new page, and scripts it adds run. Domino's script and the tab's WebSocket stay, so the new page's events work right away; its `after()` timers start, the page scrolls to the top (or to the link's `#hash`, or back where it was for back/forward), focus moves to its main heading, and its title is announced to screen readers. The page left is dropped on the server at once.

- Redirects on this site are followed, ending at the final URL (e.g. a `login_required` page sends you to `/login?next=...`). `domino.redirect()` in an event handler goes the same way.
- Anything else loads as usual: links to other sites, a response that isn't a Domino page (or a network error), links with `target`, `download` or a modifier key (to open a new tab), and `#hash` links within the page.
- While the page loads, `<html>` has `data-domino-loading` and the clicked link `aria-busy`/`data-loading`, as for events; a click on another link cancels it. The latency simulator applies too.
- `data_domino_reload=True` on a link, or any element around links, makes them load from scratch; `{"domino": {"navigation": false}}` does this for the whole app.
- Each page shown is a new page load as far as your code is concerned: components start fresh, as on a reload.
