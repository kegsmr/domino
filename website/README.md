# Domino's documentation site

The documentation is Markdown, in [docs/](../docs/): the guide's pages and the tutorial. This folder is the website that shows it, a Domino app: a home page with a live demo, the tutorial with each step's app running on the page, the guide, and search.

## Run it

From the repository root, with Domino's dependencies installed (`pip install -e .`) and the two the docs add:

```
pip install -r website/requirements.txt
python website/app.py
```

Then open http://127.0.0.1:5000. It runs in debug mode and restarts when you change a file. To serve it in production, on every CPU core:

```
domino serve website --host 0.0.0.0 --port 8000
```

The site needs no MongoDB (`settings.json` turns the development one off).

## How it's made

- `pages/` holds the pages (`pages/guide/[topic].py` is `/guide/<topic>`, `pages/tutorial/[step].py` is `/tutorial/<step>`), `pages/layout.py` the top bar, sidebar, theme and the small script for the copy buttons, the theme button and the `/` shortcut. The components (`components/`) style themselves with class-level `css`.
- **The guide is `docs/guide/*.md`.** Each page starts with `# Title` and a sentence that introduces it, then its `##` and `###` sections. `GUIDE_PAGES` in `content.py` lists the pages in the sidebar's order. Links between pages (`testing.md#mongodb-in-tests`) become links to the site's pages, and links to files (`../../examples/counter/`) go to GitHub, so the pages read the same on GitHub as on the site. A new page needs a line in `GUIDE_PAGES`.
- **The tutorial** is `docs/tutorial/<n>-<name>.md`, Markdown whose lines `{{ file: 3-styles/components/tasks.py }}` show that file and `{{ demo: 3-styles }}` run that step's `Tasks` component on the page. Each `website/tutorial/<n>-<name>/` folder is the complete app at that step; run one with `domino run --no-mongo website/tutorial/3-styles`.
- The search (`components/search.py`) looks through page titles and headings on the server as you type.

## Tests

They run with the rest of the suite (`python -m pytest` from the repository root), or on their own with `python -m pytest website`:

- `pages/*_test.py`, next to each page, drive it in Domino's simulated browser: every page renders and is marked in the sidebar, the search finds things, the demos work, dark mode and the menu button.
- `tutorial/tutorial_test.py` runs every step's app, checks that every file of those apps is shown in the tutorial (or unchanged from an earlier step) and that the commands it shows are ones `domino` accepts. `tutorial/7-testing/pages/index_test.py` is the tutorial's own test file, run like any page test.

Without Markdown and Pygments installed, the site's tests are skipped (see `conftest.py`).
