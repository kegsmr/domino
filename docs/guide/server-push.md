# Server push

Update open pages from anywhere, without waiting for an event.

`component.refresh()` re-renders a component and sends it to every open page showing it, without waiting for a browser event. It can be called from anywhere, including a background thread. There's nothing to mark: pages showing a component that gets refreshed keep a channel open for its updates (see [How the browser talks to the server](how-it-works.md#how-the-browser-talks-to-the-server)), and pages without one don't. Domino knows from the first page on when the component's own module refreshes it (`clock = Clock()` and `clock.refresh()` at its top level, or `self.refresh()` in its methods), and otherwise from its first `refresh()`; `live = True` on the class still marks one explicitly (for a component refreshed only from elsewhere, before any refresh), and `live = False` opts out. A component shown on several pages is rendered once per refresh. See `examples/clock/`.
