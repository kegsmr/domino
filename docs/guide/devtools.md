# Developer tools

Error pages, the component inspector and the event log, while debugging.

In debug mode (`domino run`, `app.run(debug=True)`), Domino helps you find what went wrong:

- **A page that fails to render** shows an error page instead of a bare 500: the exception, the traceback with the source around each line (your own frames open and marked, Flask's and Domino's folded), the component stack (`Layout › TodoList › TodoItem`, the one whose `render()` failed last), the request, and hints for common mistakes, like a `MongoNotConfigured` (how to set `mongo.url`) or a `render()` that returns something that isn't an element. A Jinja error shows the template's line.
- **A failing event handler** shows the same in the overlay: which event fired on which element and which handler ran, the frames with their source, the component stack and hints. It closes with its × or Esc.
- **The component inspector**: press <kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>D</kbd> or run `Domino.inspect()` in the browser console, hover a component to outline it, and click it. The panel shows its class and source file, its `State` values (kept up to date as the component re-renders), its attributes, the events it bound and their handlers, whether each is [instant](instant-ui.md#instant-updates) and if not, why not (`add() line 70: it reads the event...`), what its last render subscribed to, and its parents and children (click one to inspect it). `Domino.inspect(element)` inspects a given element's component.
- **The event log**, the panel's Events tab: this page's last 50 events, each with its element, handler, time on the server, round trip, size each way, and whether a predicted state was shown and matched the server's answer.
- **Startup warnings**: a debug server warns about module-level `Collection()`s (in memory, so each `domino serve` worker would have its own) and named Collections with no MongoDB to go to.

None of this exists outside debug mode: pages are byte for byte what they'd be without it (the tools are a separate script, `/_domino/debug.js`, linked only from debug pages), and its URLs answer 404. The inspector only shows a page the components it shows, asked with the page's own id. Page tests run with `app.testing` rather than debug mode, so a failing handler or page fails the test with its traceback, as before. See `examples/devtools/`.
