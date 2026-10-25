# Examples

Each example is a folder: a small `app.py`, its pages in `pages/` (`pages/index.py` is the page at `/`), and, where it helps, its components in `components/` and its data in `data.py`. Run one from the repository root, without installing Domino, then open http://127.0.0.1:5000:

```
python examples/counter/app.py
```

or, with Domino installed (`pip install -e .`), `domino run examples/counter`. `app.py` finds the repository's `domino` package by its own path, so it also works from any other folder.

The examples run in debug mode. Only `chat` stores data in MongoDB, so the others turn the development MongoDB off in their `settings.json` (`"mongo": {"auto": false}`) and don't download it; running `chat` starts one, as `domino run` does.

Some pages have their tests next to them (`pages/index_test.py` tests `pages/index.py`): see `counter`, `todo`, `search`, `forms`, `functional` and `uploads`. Run them all with `python -m pytest examples`.

| Example | Shows |
|---|---|
| `hello_world/` | A page built from tag classes, with an app-wide stylesheet served at `/style.css` and a component's own `css` |
| `functional/` | Several pages in `pages/`, a shared `layout.py` with the navigation, a page with a URL parameter (`hello/[name].py`), a `Page` class with `State` (`counter.py`) and a `404.py`. Links swap pages in without reloading (the navigation stays put and the counter works at once); the About page has a link that opts out with `data_domino_reload` |
| `counter/` | A component with `State`, re-rendered by `on_click=` |
| `random_number/` | `after(ms, ...)` updating a component on a timer |
| `clock/` | `refresh()` pushing a component to the browser from a background thread |
| `todo/` | Form submits handled in Python with `event.form`, without reloading the page |
| `forms/` | A sign-up form declared with `forms.Form`: browser and server validation, errors inline, a live email check, a password confirmation across fields and a success view with the typed values; plus a raw range input whose `event.value` re-renders only part of the page |
| `search/` | Search as you type: `on_input=..., debounce=250`, with the input keeping focus and caret while results update |
| `chat/` | Meteor-style reactivity: a shared `Collection` in `data.py`; every open window re-renders live when a message is inserted |
| `accounts/` | Sign-up, login and logout with `domino.accounts`: a `UserMenu` that updates when you log in or out, and a `login_required` page with notes only their owner sees. Needs MongoDB (started for you in debug mode) |
| `styles/` | Component `css` (nested selectors, `:hover`, `::before`, `@media`, plain CSS strings, inheritance), written once per page; a theme with a dark variant; CSS arriving with the event response that first shows a component |
| `uploads/` | File uploads: a `multiple` file input submitted with its form, read with `event.files.getlist()`, and an avatar input that uploads `on_change=`; thumbnails served back by a page (`pages/images/[id].py`) after checking the files really are images; a progress bar styled with `data-uploading` and `--domino-upload-progress` in CSS alone; tests with `page.upload()` |
| `loading/` | Styling a slow event's loading state with `[data-loading]`, and the debug error overlay when a callback raises |
| `attributes/` | `class_` for extra CSS classes, `for_` for Python keywords, `aria_*`/`data_*` attributes and `style` dicts |
| `bootstrap/` | Layout built purely from Bootstrap grid and utility mixins (`col_4` renders as `col-4`) |
| `settings/` | `app.settings` from `settings.json`, the `domino` block, and `public` settings read in the browser as `Domino.settings`. Copy `settings.local.json.example` to `settings.local.json` to override locally |
| `templating/` | A Jinja page (`home.html`, found by name, returned from `pages/index.py`) with live components inside: a counter paired with its template (`components/counter.py` + `components/counter.html`) and, on Python 3.14, a todo list written with a template string (`html(t"...")`) |
| `showcase/` | A full landing page using the imperative style (`t.h1(parent, "text")`), written as a `Page` class, styled with each component's `css`, and a contact form event |
