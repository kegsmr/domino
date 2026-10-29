# Deployment

Deploy with one command, and serve on every CPU core.

## Deploying

One command gets an app online, onto a platform you choose, from files you can read and keep:

```
domino deploy fly        # Fly.io: does everything, with Fly's flyctl command
domino deploy render     # Render: writes a Blueprint you create from Render's dashboard
domino deploy docker     # a Docker image, to run anywhere
```

Each takes the app's folder (default: the current one). Every one of them first runs `domino build`, which writes into the app's folder:

- `Dockerfile`: Python 3.12 (slim), the app's `requirements.txt` installed with `domino-web` pinned to the version you're running, the app run by a user without root rights, `domino serve` on port 8000, and a health check.
- `.dockerignore`, which keeps `.domino/`, `settings.local.json`, `.env`, `.git`, virtualenvs and caches out of the image.
- `requirements.txt`, if the app has none: just `domino-web==<version>`. Add the app's other dependencies to it.

Files that are already there are kept (`--force` writes them again, except `requirements.txt`, which is always yours), so you can edit them. Commit them with the app. The app serves `GET /_domino/health` (it answers `ok` without making a page), which the platforms use to check it's up. The number of worker processes is one per CPU core, or `WEB_CONCURRENCY` if it's set.

**Fly.io.** `domino deploy fly` writes `fly.toml` (port 8000, HTTPS only, health checks on `/_domino/health`, one shared CPU with 512MB; the app gets the folder's name with a random ending, or `--name`). If `flyctl` is installed ([install it](https://fly.io/docs/flyctl/install/)), it then logs you in if needed, creates the app the first time (`fly launch --no-deploy --copy-config`), sets the app's secrets with `fly secrets set`, and runs `fly deploy`. The app ends up at `https://<name>.fly.dev/`, which `fly.toml` sets as `DOMINO_PUBLIC_URL` (change it for a domain of your own); it also trusts `X-Forwarded-For` from Fly's proxy alone (`FORWARDED_ALLOW_IPS`, private networks), so login and email limits see each visitor's address. Without `flyctl`, it prints these commands to run yourself. Run it again to deploy a new version.

**Render.** `domino deploy render` writes `render.yaml`, a [Blueprint](https://render.com/docs/blueprint-spec): a Docker web service with its health check, a generated `DOMINO_SECRET_KEY`, a `DOMINO_MONGO__URL` for you to fill in, and `FORWARDED_ALLOW_IPS` trusting Render's proxy (add `DOMINO_PUBLIC_URL` if the app sends email). Render creates services from Blueprints in its dashboard, not from your computer, so then: push the repository to GitHub (or GitLab or Bitbucket), choose **New > Blueprint** in the Render dashboard, pick the repository, and enter your MongoDB URL when asked. Later pushes deploy by themselves. For an app in a subfolder of its repository, the paths in `render.yaml` are set for that, and you point Render at the subfolder's `render.yaml`.

**Docker.** `domino deploy docker` builds the image (if Docker is running) and prints the `docker run` command, with the environment variables it needs. It also writes `docker-compose.yml`, which runs the app together with a MongoDB of its own (a single-node replica set, its data in a Docker volume): `export DOMINO_SECRET_KEY=...` and then `docker compose up -d` serves it on http://localhost:8000. Any host that runs containers can run the image.

**MongoDB.** Named collections (`Collection("tasks")`) need a MongoDB in production, and it must be a replica set, since live updates come from its change streams. [MongoDB Atlas](https://www.mongodb.com/cloud/atlas) clusters are, including the free one: copy its connection string (`mongodb+srv://...`) and give it to `domino deploy` with `--mongo-url`, or have it in `DOMINO_MONGO__URL` (or `MONGO_URL`), or in `settings.local.json` as `mongo.url`. `domino deploy fly` asks for it when it finds none, and passes it to Fly as a secret. `domino deploy` warns when the app's code uses named collections (it looks for `Collection("` in its `.py` files) and no MongoDB URL is set. The development MongoDB's URL (`127.0.0.1`) is never used for production.

**The secret key.** Logins and sessions need a `secret_key`. `domino deploy fly` makes a random one and sets it as the Fly secret `DOMINO_SECRET_KEY` the first time (later deploys keep it, so nobody is signed out; one in your `DOMINO_SECRET_KEY` environment variable is used instead if set), and Render generates one. Secrets are only passed to the platform's commands or printed, never written into the app's files. Keep `secret_key` out of `settings.json`, which is committed with your code; `domino deploy` warns when it's there.

**One instance.** A page lives in the memory of the server process that made it, so an app runs on one machine (with a worker process per CPU): `domino deploy fly` deploys a single machine (`--ha=false`), and Render's service has one instance. Choose a bigger machine to serve more. The session cookie is only sent over HTTPS (Fly and Render serve HTTPS); to try an image over plain `http://localhost`, add `-e DOMINO_DOMINO__SECURE_COOKIES=false` (`docker-compose.yml` sets it).

## Serving in production

`domino serve` is what the Dockerfile runs, and works on any server:

```
domino serve myapp --host 0.0.0.0 --port 8000
```

It uses every CPU core, with nothing to set up. It starts one worker process per core (`--workers N` to choose), each with its own copy of the app, and listens on the port itself, passing each request to a worker. It's for production, so it doesn't reload on changes or start a development MongoDB: set `mongo.url` (e.g. `DOMINO_MONGO__URL`). An app using Tailwind gets its minified CSS built first (run `domino tailwind build` when building an image; see [Tailwind in production](tailwind.md#tailwind-in-production)).

A page lives in the memory of the worker that rendered it: its components, their state and their event handlers. So a tab's events must reach that worker, and they do, without sticky sessions or anything else to configure: each page id starts with its worker's number (`w3-...`), and `domino serve` sends every request about a page to the worker the id names. New page loads go to the least busy worker. The same goes for the token a login over the WebSocket hands the browser.

- If a worker crashes, it's started again. Its pages are gone, so their tabs reload, as after a restart. Ctrl+C or `SIGTERM` stops the workers, letting them finish what they're doing; if `domino serve` itself is killed, its workers stop too.
- Named collections (`Collection("messages")`, MongoDB) are shared: a change made in any worker re-renders the components showing it in every worker, through MongoDB's change streams (which need a replica set).
- Everything else in Python memory is per worker: `Collection()` without a name, module-level `State`, caches, the failed-login counts. Two tabs on different workers don't see each other's in-memory data, so keep what users share in MongoDB.
- A background thread the app starts (like `examples/clock/`'s) runs in each worker, and its `refresh()` updates that worker's pages.
- Workers load the app side by side, so starting takes about as long as with one.

`domino serve --workers 1` serves one process with no router, as does uvicorn itself: `uvicorn app:app.asgi --host 0.0.0.0 --port 8000`. `app.run(workers=4)` (without debug mode) is the same as `domino serve --workers 4`, for an app defined at the top level of its file.

Behind a proxy such as nginx (for HTTPS, say), let it pass WebSockets for `/_domino/ws` (with nginx: `proxy_http_version 1.1` and the `Upgrade`/`Connection` headers). Workers see the visitor's address in `request.remote_addr`; as with uvicorn, an `X-Forwarded-For` header is believed only from the addresses or networks in `FORWARDED_ALLOW_IPS` (default `127.0.0.1`; e.g. `127.0.0.1,10.0.0.0/8`). List your proxies rather than `*`, which makes the visitor's own first `X-Forwarded-For` entry count (see SECURITY.md). Plain WSGI servers (`gunicorn app:app`) work too, with the HTTP fallback above, but then each tab showing a live component holds a server thread, and several worker processes need sticky sessions.

Each page load gets its own state, which expires after `DOMINO_PAGE_TTL` seconds of inactivity (default 1800). At most `DOMINO_MAX_PAGES` pages are kept per worker (default 1000); when a page has expired, the browser reloads it. To change how pages are kept, subclass `domino.PageStore` (or `MemoryPageStore`) and pass `Domino(__name__, page_store=...)`.
