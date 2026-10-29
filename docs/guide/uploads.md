# File uploads

File inputs whose files arrive in your handler.

A file input works like any other field: its files arrive in the handler as `event.files`, a werkzeug `MultiDict` of uploaded files (werkzeug's `FileStorage`, plus `size` in bytes):

```python
class Avatar(t.div):

    def render(self):
        return [
            t.form(on_submit=self.save) [
                t.input(type="file", name="photo", accept="image/*"),
                t.input(type="file", name="extras", multiple=True),
                t.button() ["Upload"],
            ],
            t.input(type="file", name="quick", on_change=self.quick),  # uploads as soon as a file is picked
        ]

    def save(self, event):
        photo = event.files["photo"]                 # or event.files.get("photo"), None if none was picked
        photo.filename, photo.content_type, photo.size
        photo.save(path)                             # or photo.read(), photo.stream
        for file in event.files.getlist("extras"):   # a multiple input
            ...

    def quick(self, event):
        file = event.files["quick"]
```

- A form's submit sends the files of every file input in it; a file input's own event (`on_change=`) sends its files. Other events (a click inside the form) send none. A file input without a `name` sends its own files as `"file"`.
- Files go up in a multipart POST of their own to `/_domino/upload`, never through the WebSocket, and the event follows with a token per file; the handler gets the files themselves. A token only works for the page that uploaded it, only once, and expires after `{"domino": {"upload_ttl": 600}}` seconds. Files over 500 KB are spooled to temporary files, not held in memory, and every file is deleted once its event has been handled (or expired unclaimed): `save()` or copy what you want to keep.
- `{"domino": {"max_upload_mb": 16}}` (the default) limits each upload request, all its files together. A bigger one is refused with status 413 and the event isn't sent; the browser reports it like a failed event (the `domino:error` event, and the error overlay in debug mode). Uploads waiting for their event are capped too: two uploads' worth per page and `{"domino": {"max_pending_uploads_mb": 256}}` for all pages together, the oldest going first. Events themselves (their JSON, over HTTP or the WebSocket) are limited by `{"domino": {"max_event_mb": 1}}`.
- `filename`, `content_type` and `accept="image/*"` come from the browser and can't be trusted: check the content yourself, and use `werkzeug.utils.secure_filename` before putting a filename in a path. Handlers that use files are never predicted (see [Instant updates](instant-ui.md#instant-updates)).
- Uploads can't be sent from other sites: `/_domino/upload` requires an `X-Domino-Page` header with a live page's id, which a form on another site can't add (and another site's script can't without a CORS preflight, which Domino never allows).
- After a successful submit, the form's file inputs are cleared like its other fields.

While its files go up, the element that fired (and its form) has `data-uploading` set to the percentage sent so far and the CSS variable `--domino-upload-progress`, from 0 to 1. `data-loading` and `aria-busy` are set as for any event, until the event's response arrives. A progress bar and a label, with CSS alone:

```python
css = {
    "form[data-uploading]::after": {
        "content": "''", "display": "block", "height": "6px", "background": "#2a7",
        "width": "calc(var(--domino-upload-progress) * 100%)",
    },
    "form[data-uploading]::before": {"content": "'Uploading ' attr(data-uploading) '%'"},
}
```

The latency simulator delays uploads too (a round trip of their own before the event's). See `examples/uploads/`.
