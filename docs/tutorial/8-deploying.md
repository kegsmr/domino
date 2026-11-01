# Deploying

Serve the app in production, on every CPU core, with one command.

## domino serve

```bash
domino serve tasks --host 0.0.0.0 --port 8000
```

`domino serve` starts one worker process per CPU core (`--workers 4` picks the number), each with its own copy of the app, and listens on the port itself. It doesn't reload when files change, and it doesn't start a MongoDB: production uses yours.

A page lives in the memory of the worker that rendered it, with its components and their state, so its events must reach that worker. They do, without sticky sessions or a load balancer to configure: each page's id names its worker, and `domino serve` routes every request about a page to it. Tasks are in MongoDB, which every worker shares, so a task added through one worker re-renders the pages of all the others.

## Settings from the environment

The app needs two settings in production: the database, and the secret that signs session cookies. Any setting can come from an environment variable, `DOMINO_` followed by its name, with `__` for nesting:

```bash
export DOMINO_MONGO__URL="mongodb://db.example.com:27017/tasks?replicaSet=rs0"
export DOMINO_SECRET_KEY="a long random string"
domino serve tasks --host 0.0.0.0 --port 8000
```

They can also go in `settings.json` in the app's folder, and `settings.local.json` next to it for what shouldn't be committed. Use a replica set, so changes made through one worker reach the pages of the others.

## Behind a proxy

For HTTPS, put a proxy such as nginx or Caddy in front, and let it pass WebSockets for `/_domino/ws`, which each browser tab uses to talk to its page. In production the session cookie is only sent over HTTPS.

That's the whole app: pages, components, live data, accounts and tests, with no JavaScript, no API and no build step. The [guide](../README.md) covers everything else, starting with [Components](../guide/components.md). This docs site is a Domino app too: its source is in `website/` in the repository, and `domino serve website` serves it.
