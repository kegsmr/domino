# Reactive data

Share the list between everyone, live: a Collection re-renders every page that shows it. In memory first, then in MongoDB.

## A Collection

So far each visitor has their own list, in their own component. To share one, keep the tasks in a `Collection`, in a module of their own, `data.py`, next to `pages/`:

{{ file: 5-reactive-data/data.py }}

Then use it in the component instead of `State`:

{{ file: 5-reactive-data/components/tasks.py }}

`tasks.find(...)` returns the documents (dicts) matching a query, here all of them, oldest first. `insert`, `update` and `remove` change them, with MongoDB's query syntax (`{"_id": id}`, `{"done": True}`, `{"$set": ...}`).

## Every page updates

Reading the collection in `render()` subscribes the component. When a handler changes the collection, every subscribed component re-renders, on every open page, and Domino pushes the result to each browser. That's the whole sync layer: no polling, no API, no client-side store.

The demo below is shared by everyone reading this page right now. Open this page in a second window and add a task in one: it shows up in the other.

{{ demo: 5-reactive-data }}

The person who made a change gets their response straight away; the other pages are re-rendered just after, in the background.

## In MongoDB

`Collection()` without a name lives in the server's memory: it's gone on a restart, and each server process has its own. Give it a name and it's a MongoDB collection instead. Nothing else changes:

{{ file: 5-mongodb/data.py }}

Now run the app without `--no-mongo`:

```bash
domino run tasks
```

`domino run` downloads MongoDB the first time (about 100 MB, then cached in `~/.domino/`), and runs it for the app, with its data in `tasks/.domino/`. It runs MongoDB as a replica set, so Domino can watch each collection's change stream: a change made by another server process, a script or `mongosh` re-renders the pages too. In production you point the app at your own database with the `mongo.url` setting; see [Reactive data & MongoDB](../guide/reactive-data.md).
