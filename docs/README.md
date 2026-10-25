# Domino's documentation site

The docs are a Domino app: a home page with a live demo, a tutorial whose steps are real apps running on the page, and a guide made from the repository's [README.md](../README.md).

## Run it

From the repository root, with Domino's dependencies installed (`pip install -e .`) and the two the docs add:

```
pip install -r docs/requirements.txt
python docs/app.py
```

Then open http://127.0.0.1:5000. It runs in debug mode and restarts when you change a file. To serve it in production, on every CPU core:

```
domino serve docs --host 0.0.0.0 --port 8000
```

The docs need no MongoDB (`settings.json` turns the development one off).

## How it's made

- `pages/` holds the pages (`pages/guide/[topic].py` is `/guide/<topic>`, `pages/tutorial/[step].py` is `/tutorial/<step>`), `pages/layout.py` the top bar, sidebar, theme and the small script for the copy buttons, the theme button and the `/` shortcut. The components (`components/`) style themselves with class-level `css`.
- **The guide is README.md.** `content.py` splits README.md into its `##` and `###` sections when the app starts, and `GUIDE` lists which sections each guide page shows. README links (`#testing-your-app`) are pointed at the guide page that has the section, and links to files at GitHub. A test checks that every README section is on some page, so a new section needs a line in `GUIDE`. Change the docs by changing README.md.
- **The tutorial** is `tutorial/<n>-<name>.md`, Markdown whose lines `{{ file: 3-styles/components/tasks.py }}` show that file and `{{ demo: 3-styles }}` run that step's `Tasks` component on the page. Each `tutorial/<n>-<name>/` folder is the complete app at that step; run one with `domino run --no-mongo docs/tutorial/3-styles`.
- The search (`components/search.py`) looks through page titles and headings on the server as you type.

## Tests

They run with the rest of the suite (`python -m pytest` from the repository root), or on their own with `python -m pytest docs`:

- `pages/*_test.py`, next to each page, drive it in Domino's simulated browser: every page renders and is marked in the sidebar, the search finds things, the demos work, dark mode and the menu button.
- `tutorial/tutorial_test.py` runs every step's app, checks that every file of those apps is shown in the tutorial (or unchanged from an earlier step) and that the commands it shows are ones `domino` accepts. `tutorial/7-testing/pages/index_test.py` is the tutorial's own test file, run like any page test.

Without Markdown and Pygments installed, the docs' tests are skipped (see `conftest.py`).
