# Domino

An experimental Python web framework built on Flask. It currently resembles a glorified HTML/CSS generator, but more features are planned.

**This project is a work-in-progress! Not all features are functional yet.**

## Install

The distribution is named `domino-web`; the import name is `domino`.

```
pip install -e .
```

## Run an example

From the repository root:

```
python examples/counter.py
```

Then open http://127.0.0.1:5000.

## Tests

```
pip install -e .[test]
python -m pytest
```

## Releasing

Bump `version` in `setup.py`, then publish a GitHub Release (e.g. tag `v0.1.0`). The `Publish to PyPI` workflow builds the package and uploads it to PyPI as `domino-web`.
