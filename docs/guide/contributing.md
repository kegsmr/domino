# Contributing

Run Domino's own tests, publish a release, and the license.

## Tests

```
pip install -e .[test]
python -m pytest
```

Tests marked `mongo` are skipped unless `DOMINO_TEST_MONGO_URL` points at a MongoDB replica set, e.g. `DOMINO_TEST_MONGO_URL="mongodb://127.0.0.1:27017/?replicaSet=rs0" python -m pytest`. The examples' page tests use it too, or else start a `mongod` themselves (see [MongoDB in tests](testing.md#mongodb-in-tests)).

## Releasing

Bump `version` in `setup.py`, then publish a GitHub Release (e.g. tag `v0.1.0`). The `Publish to PyPI` workflow builds the package and uploads it to PyPI as `domino-web`.

## License

MIT, copyright (c) 2026 Kegan Messmer. See [LICENSE.txt](../../LICENSE.txt).
