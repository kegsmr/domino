# Client components

Experimental: components that run in the browser, in Python.

## Experimental: client components

A component with `client = True` runs in the browser, in Python: the server renders its first HTML, then MicroPython compiled to WebAssembly (about 190 KB, loaded only on pages that need it) takes over, so its handlers, re-renders and `after()` timers never wait for the server and keep working offline. The API is the same (`State`, `render()`, `on_click=`, class-level `css`), and `self.emit("save", value)` runs a handler the server component around it passed in (`Sketch(on_save=self.save)`).

```python
class Counter(t.div):

    client = True
    count = State(0)

    def render(self):
        return [t.button(on_click=self.increment) [f"Clicked {self.count} times"]]

    def increment(self):
        self.count += 1
```

**The component's whole module is sent to the browser and is public**: it may only import `domino.tags`, `State` and `math`, `random`, `time`, `json` (anything else, like a `Collection` or your server modules, stops the app at startup), and must never hold server-only code or secrets. The runtime comes from jsDelivr, or while debugging from a copy downloaded once into `~/.domino/client-runtime` (`{"domino": {"client_runtime": "local" | "cdn" | "<url>/", "client_python": "micropython" | "pyodide"}}`). It's a prototype: see [docs/research/client-python.md](../../docs/research/client-python.md) for what works, measurements, limitations and open problems, and `examples/client/`.
