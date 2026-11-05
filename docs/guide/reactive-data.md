# Reactive data & MongoDB

Collections that re-render every open page when they change.

## Reactive data

Domino components re-render themselves when the data they show changes. Reading a `State` or querying a `Collection` inside `render()` subscribes the component; changing it re-renders every subscribed component on every open page and pushes the result (no `live = True` needed):

```python
from domino import Collection, State

messages = Collection("messages")   # shared by everyone
online = State(0)

class Chat(t.ul):

    def render(self):
        return [t.li() [m["text"]] for m in messages.find(sort=[("sent", -1)], limit=50)]

    def send(self, event):
        messages.insert({"text": event.form["text"], "sent": time.time()})  # every Chat updates
```

- `State(value)`: `.value` reads (and subscribes), `.value = x` changes it.
- `Collection(name)`: `insert(doc)` (returns the `_id`), `find(query, sort=..., limit=...)` (a cursor you iterate or `.fetch()`), `find_one`, `count`, `update(query, {"$set": ...}, multi=False)` and `remove(query)`, with MongoDB-style queries (`$gt`, `$in`, `$or`, dotted paths, ...). Documents come back as copies.
- `raw_collection()` and `raw_database()` (named collections only): the pymongo collection and database, for what `Collection` doesn't do, such as indexes and aggregation (`tasks.raw_collection().create_index("created")`). Writes made through them still update open pages, through MongoDB's change stream.
- A component re-renders only when a change can change what its queries found: the changed document matches the query now, or it was in the last result (so it may have left it, or been deleted). With `tasks.find({"done": False})`, marking a finished task as done again, or adding a done one, re-renders nothing. With a `limit`, a change to any matching document counts, since it may enter the top N.
  - In MongoDB, Domino decides this with the in-memory matcher only where MongoDB would agree: plain values (strings, numbers, booleans, and never a boolean against a number, or NaN) on fields that hold no lists, with the operators the in-memory collection supports, in a collection without a default collation. Anything else (`$regex`, `$elemMatch`, a field holding a list, `None`, dates, `ObjectId`s, a dropped collection) re-renders every subscriber, as it always has. So does an update or delete made in this process without a replica set, since MongoDB doesn't say which documents it changed.
- Changes made while handling an event re-render each subscriber once, in the background, so the user who made the change gets their response straight away. Use `with batch():` to group changes made elsewhere, and `domino.wait()` in tests to let background updates finish.

See `examples/chat/`.

## MongoDB

Named collections live in MongoDB: `Collection("messages")` is the `messages` collection of the app's database, and `Collection()` without a name is an in-memory collection for this process only. Queries and updates use MongoDB's own syntax (all of it, not just the subset the in-memory collection supports). Documents get a string `_id` unless they have one.

The database comes from the `mongo.url` setting (e.g. `DOMINO_MONGO__URL=mongodb://db:27017/myapp?replicaSet=rs0`), with the database name taken from the URL (default `domino`); `MONGO_URL` works too, and `domino.mongo.connect(url)` sets it in code. When MongoDB runs as a replica set, a change stream per collection re-renders subscribers when *any* process changes the collection — another server process, a script, or `mongosh` — so it also works with several server processes. Without a replica set only this process's own writes update pages live.
