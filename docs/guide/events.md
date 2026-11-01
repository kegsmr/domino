# Events

Clicks, typing and submits, handled in Python on the server.

`element.bind("click", callback)` (or `on_click=callback`) runs `callback` on the server. A callback that takes an argument receives an `Event`:

- `event.type`: the DOM event name (`"click"`, `"submit"`, `"change"`, ...)
- `event.value`: the element's value (`True`/`False` for checkboxes)
- `event.form`: the surrounding `<form>`'s fields as a dict of strings (repeated names become lists of strings; anything else a client sends is dropped, so a field can't smuggle a MongoDB operator like `{"$ne": null}` into a query)
- `event.files`: uploaded files (see [File uploads](uploads.md#file-uploads))

Submit events don't reload the page. See `examples/todo/`.

`bind(event, callback, debounce=ms)` waits until the user pauses before sending, which suits `"input"` events (see `examples/search/`). An element can have several events.

Updates are patched into the page in place rather than replacing the component's HTML, so focus, the caret and anything the user is typing survive a re-render. Form fields keep what the user entered unless the server changes their value, or they belong to the element whose event was just handled (a submitted form is reset to what the server renders).

## Loading and errors

While an event's request is in flight, the element that fired it gets `aria-busy="true"` and `data-loading` (for a submit, so do the form's submit buttons), and `<html>` gets `data-domino-loading`. Buttons, selects and other controls are also disabled until the response is applied, unless they were disabled already; text fields that fire debounced `input` events are not, so typing continues. Domino adds no styles for this, so add your own:

```python
page.style("button[data-loading]", opacity="0.6", cursor="progress")
page.style("html[data-domino-loading]", cursor="progress")
```

If a callback raises, the server logs the exception and answers with status 500. In production the response only says `"Internal Server Error"`; with `app.debug` on it includes the exception and its traceback, and the browser shows them in an overlay (see [Developer tools](devtools.md#developer-tools)). Either way the browser dispatches a cancelable `domino:error` event on the element that fired, which bubbles to the document, with `detail` holding `error`, `traceback` (debug only) and `eventId`. Cancel it to handle errors yourself:

```js
document.addEventListener('domino:error', (e) => {
    e.preventDefault();  // no overlay or console.error
    showToast('Something went wrong');
});
```

See `examples/loading/`.
