# Your first page

A page, a component, and state that re-renders it: the whole idea of Domino in two files.

## Install

You need Python 3.9 or newer. Install Domino in a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install domino-web
```

## A page

Make a folder for the app, `tasks/`, with a `pages/` folder inside. Every Python file in `pages/` is a page, and its path is its URL: `pages/index.py` is the page at `/`. A page file has a `page()` function that returns what to show, built from tag classes: `t.h1` is an `<h1>`, and what's in the square brackets goes inside it. With attributes, call it first: `t.a(href="/about") ["About"]`.

{{ file: 1-first-page/pages/index.py }}

The page imports `Tasks` from `components/`, which you write next. The app's folder is on the import path, so pages can import anything in it.

## A component

A component is a Python class that subclasses `Component` (it renders as a `<div>`; `tag = "section"` picks another element). Its `render()` returns what goes inside, and its `State` attributes hold what can change:

{{ file: 1-first-page/components/tasks.py }}

`on_click=self.add` binds the button's click to a method. The method runs on the server, changes `self.items`, and Domino re-renders the component and sends the browser only what changed. You don't write any JavaScript, and there's no API in between: the click handler is a method of the thing on screen.

Here it is, running on this page:

{{ demo: 1-first-page }}

## Run it

From the folder that contains `tasks/`:

```bash
domino run --no-mongo tasks
```

Open http://127.0.0.1:5000. `domino run` serves the app in development and restarts it when you save a file. `--no-mongo` skips the local MongoDB it would otherwise start for you, which you won't need until step 5. A folder with just `pages/` is enough: no `app.py`, no settings.

Every visitor gets their own `Tasks`, and so their own list: open a second window and the lists are separate. Step 5 makes them shared.
