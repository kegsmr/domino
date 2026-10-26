# Server push

Update open pages from anywhere, without waiting for an event.

`component.refresh()` re-renders a component and sends it to every open page showing it, without waiting for a browser event. It can be called from anywhere, including a background thread. Mark components that will be refreshed with the class attribute `live = True`, so pages showing one listen for updates (see [How the browser talks to the server](how-it-works.md#how-the-browser-talks-to-the-server)); pages without one don't. A component shown on several pages is rendered once per refresh. See `examples/clock/`.
