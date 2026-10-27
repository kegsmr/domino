# Installation

Install Domino and run the examples.

## Install

The distribution is named `domino-web`; the import name is `domino`. It needs Python 3.9 or newer, on Linux, macOS or Windows.

```
pip install domino-web
```

Then make an app and run it:

```
domino create myapp
cd myapp
domino run
```

Open http://127.0.0.1:5000. The first run downloads a MongoDB for development (see [Development MongoDB](cli.md#development-mongodb)); later runs start at once. `domino create myapp --minimal` makes a one-page app that needs no MongoDB, so it starts at once the first time too.

- If `domino` isn't found after installing (common with the Microsoft Store's Python on Windows), use `python -m domino` instead: `python -m domino run`.
- To work on Domino itself, install it from a clone instead: `pip install -e .[test]`.

**`CERTIFICATE_VERIFY_FAILED` on macOS.** Python from python.org can't verify HTTPS sites (such as the MongoDB download) until its certificates are installed. Run this once per Python version, then try again:

```
open "/Applications/Python 3.9/Install Certificates.command"
```

## Run an example

```
python examples/counter/app.py
```

Then open http://127.0.0.1:5000. Each example is a folder with a small `app.py` and its pages in `pages/`; see [examples/README.md](../../examples/README.md).
