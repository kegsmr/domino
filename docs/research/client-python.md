# Client components: Python that runs in the browser

*Prototype and feasibility study, 2026-10-25. Follows up on issue #23 ("Research: client-side Python, the competition, and how Domino can win"), option (d).*

**Status: experimental.** A component with `client = True` is rendered once by the server and then runs in the browser on MicroPython compiled to WebAssembly. It keeps the same Python API: `State`, `render()` returning tags, `on_<event>=` handlers, `after()` timers and class-level `css`. Code: `domino/client.py`, `domino/client.js` and `domino/client_shim/`. Example: `examples/client/`. Tests: `tests/test_client.py`, `tests/test_client_browser.py` and `examples/client/pages/index_test.py`.

## Summary

- **The approach works end to end.** The server renders the first HTML (SSR) with the same Python code the browser will run, so the page works before anything loads. Then a 190 KB runtime starts in about 0.1 s and the component runs in the tab. Clicks, keystrokes and timers never wait for the server. With the server stopped and every request blocked, the example's Game of Life keeps ticking at about 27 generations per second and its text statistics keep updating. A client component can sit inside a server component. It reaches the server by `self.emit("save", value)`, which runs a handler the server component passed in (`Life(on_save=self.save)`). That server handler never leaves the server.
- **I chose MicroPython as the default runtime.** It's the only real Python that is small and fast to start: about 193 KB brotli, with 34–73 ms init in Chromium. Pyodide runs the same components unchanged and is fully compatible. It's an opt-in setting (`client_python: "pyodide"`) for compute-heavy islands, at 5.3 MB brotli and 3–6 s startup. I measured Brython and rejected it: 1 MB brotli and 8–10 s startup here. I also rejected a Python-to-JS transpiler for whole components: it would only cover a small subset of what components actually do (see below).
- **The cost is speed.** MicroPython runs the example's render about 20x slower than CPython: about 27 ms for 400 elements against 1.4 ms. About 400 elements re-rendered per frame is a practical ceiling at 30 fps. For text widgets, forms, menus, editors and small games that is plenty. For big lists or canvas-style graphics it isn't.
- **Recommendation:** keep it as an explicit, experimental opt-in island feature. Don't make it a default rendering mode, and keep the server authoritative for anything that matters. The next steps are listed at the end.

## What the prototype does

```python
# components/life.py: this whole file is sent to the browser
import domino.tags as t
from domino import State


class Life(t.div):

	client = True                 # runs in the browser

	cells = State([0] * 400)
	running = State(False)

	css = {".board span.on": {"background": "var(--accent)"}}   # still written by the server


	def render(self):

		if self.running:
			self.after(33, self.tick)     # 30 generations a second, computed in the browser
		return [
			t.div(class_="board")([
				t.span(class_="on" if cell else None, on_click=lambda event, index=index: self.toggle(index))
				for index, cell in enumerate(self.cells)
			]),
			t.button(on_click=self.save) ["Save to server"],
		]

	...

	def save(self):

		self.emit("save", {"cells": self.cells})   # runs the server's on_save=... handler
```

```python
# components/patterns.py: a server component around it
class Patterns(t.section):

	saved = State([])

	def render(self):
		return [Life(on_save=self.save), t.ol()([t.li() [str(p)] for p in self.saved])]

	def save(self, event):            # on the server, with event.value from the browser
		self.saved = self.saved + [len([c for c in event.value["cells"] if c])]
```

### How it works

1. **Marking.** `Element.__init_subclass__` sees `client = True` and calls `domino.client.register()` when the class is defined. That happens when pages are imported, which is when the app is created.
2. **Extraction and validation.** The unit sent to the browser is **the component's whole module file**, not just the class. Classes use module-level constants and helpers (`SIZE`, `START`, `now()` in the example), and a file is a clear public/private boundary, like React's `"use client"` files. The file is parsed with `ast`, and every import, including those inside functions, must be `domino.tags`, `State`/`tags` from `domino`, or one of `math`, `random`, `time`, `json`. Anything else stops the app at startup, for example:

   ```
   ClientComponentError: /app/components/life.py:9: Life has client = True, so all of components/life.py is sent
   to the browser, and it can't import Collection from domino: Collections live on the server; pass the data in
   as State, or send it to the server with self.emit(). In the browser there are only domino.tags, State (from
   domino) and the modules json, math, random, time. Keep server code in another module.
   ```

   `State` defaults must be JSON. `live = True` is refused. A server-side subclass with `client = False` is an ordinary server component. The example uses one to run the very same `TextStats` class both ways.
3. **The shim.** `domino/client_shim/domino/` is a small `domino` package (about 17 KB of source) written in the common subset of MicroPython and CPython. It has `State`, the tag classes, an HTML renderer and the runtime entry points (`load_module`, `mount`, `dispatch`, `html`). In the browser it's written to the runtime's virtual file system, so a component's `import domino.tags as t` gets it.
4. **SSR with the browser's code.** On the server, `Element._render` hands client components to `domino.client.render()`. That function loads the same shim in CPython, under a private module name, and runs the component's module against it, mapping `import domino` to the shim through a custom `__import__`. The first HTML is therefore made by exactly the code the browser runs. A test checks that the browser's first render equals the SSR, apart from the hand-over attributes. The root carries `data-domino-client="<module>@<hash>:<Class>"` and `data-domino-state` (the State values and attributes as JSON). Class-level `css` goes into the page's `<head>` as for any component.
5. **Hydration.** `core.js` gets two small changes. `listen()` imports `/_domino/client/loader.js` when the page (or an update) contains `[data-domino-client]`. `morphChildren()` leaves a running client component alone when the server re-renders what's around it. The loader (`domino/client.js`, with its `CONFIG` prepended by the server, including the shim's source) starts the runtime once and fetches each module from `/_domino/client/module/<name>.py?v=<hash>`, which is immutable-cached and only serves registered client modules. It then calls `mount()`.
6. **Events, re-render, morph.** `on_click=` in a client render becomes `data-domino-on="click:<n>"`, not a server event. The loader listens on the component's root (capturing), builds an `Event` (`type`, `value`, `form`, `data` from `data-*`, pointer `x`/`y`, `key`), and calls `dispatch()`. If the handler changed State, the component renders again and the HTML is morphed in with `Domino.morph`, the same morph server updates use, so focus and typing survive. `after(ms, fn)` timers run with `setTimeout`, one per `after()` call site, and the delay counts from when the handler started. Errors raise a cancelable `domino:error`, like failed server events, with the Python traceback.
7. **Calling the server.** `self.emit(name, value)` triggers the server event that the parent bound on the client component's root (`Life(on_save=self.save)` puts `data-event-id="…-save"` there). The event goes through `Domino.triggerEvent`, over the WebSocket or POST, with loading marks, ordering and errors as usual. The server's answer re-renders the parent, and the running island is kept.

### Serving the runtime

| Setting (`settings.json` → `domino`) | Default | Meaning |
|---|---|---|
| `client_python` | `"micropython"` | or `"pyodide"` |
| `client_runtime` | `"local"` in debug mode, `"cdn"` otherwise | `"cdn"`: jsDelivr (`https://cdn.jsdelivr.net/npm/<package>@<version>/`); `"local"`: served by the app at `/_domino/client/runtime/` from `~/.domino/client-runtime/` (or `$DOMINO_HOME`); any URL ending in `/`: your own copy |
| `client_heap_mb` | `16` | MicroPython's heap |

Nothing big is in the repository. With `"local"`, the npm package (MicroPython `@micropython/micropython-webassembly-pyscript@1.29.0-6`, or `pyodide@314.0.7`) is downloaded on first use. It comes from the npm registry with `urllib`, or through `npm pack` when that fails. It's checked against a **pinned sha512**, and only the needed files are kept. This is the same pattern devmongo uses for MongoDB: a file lock, atomic replace, and offline once cached. The browser tests use this copy.

## Measurements

**Setup.** The server was a 2-vCPU Xeon container that was **shared with other test runs**: load average 2–4 during the runs, so the numbers are noisy. I give the min–max of 3 runs. The browser was headless Chromium 153 (Playwright), with cold contexts. The server was local, so network transfer time is **excluded**: in real use, add about 0.2 MB (MicroPython) or 5.3 MB (Pyodide) of download. The npm packages were `@micropython/micropython-webassembly-pyscript@1.29.0-6`, `pyodide@314.0.7` and `brython@3.15.0`. The scripts are in the session scratchpad (not committed): `bench/measure.py` and `bench/probe.py` for the bare runtimes, `measure_domino.py` and `profile_frame.py` for the example, and `subset.py` for the transpiler estimate.

### Download size

| Runtime | Files | Raw | gzip -9 | brotli -11 |
|---|---|---|---|---|
| MicroPython (wasm) | `micropython.mjs` + `micropython.wasm` | 547 KB | 226 KB | **193 KB** |
| Pyodide | `pyodide.js`, `pyodide.asm.mjs`, `pyodide.asm.wasm`, `python_stdlib.zip`, `pyodide-lock.json` | 13,215 KB | 6,241 KB | **5,336 KB** |
| Brython | `brython.min.js` + `brython_stdlib.js` | 5,892 KB | 1,300 KB | **1,014 KB** |
| Transpiled subset | nothing (compiled JS per component) | 0 | 0 | 0 |
| *Domino's part* | `loader.js` (loader + shim, 27.7 KB raw), plus the module (`life.py`: 4.2 KB raw) | 32 KB | 10.6 KB | **9.4 KB** |

For comparison, `core.js` is 11.7 KB brotli.

### Startup in the browser (no network)

| | Init of the bare runtime | Domino example: runtime + shim ready | Navigation → component hydrated |
|---|---|---|---|
| MicroPython | 34–73 ms | 85–149 ms | 380–540 ms |
| Pyodide | 3.6–6.2 s | 3.0–5.8 s | 3.9–7.0 s |
| Brython (with stdlib) | 8.0–10.2 s | – | – |

### How much Python works (51-check probe of features Domino components use)

| | Passed | Failures |
|---|---|---|
| Pyodide | **51/51** | – |
| Brython | 50/51 | non-ASCII `str.lower()` |
| MicroPython | **34/51** | writing `instance.__dict__` (read-only); `__mro__`; dict and `**kwargs` insertion order; `vars()`; bound method `__self__`; `__code__.co_argcount` / `inspect.signature`; `__init_subclass__`; non-ASCII `str.lower()`; `re.findall` / `re.split`; `dataclasses`, `typing`, `collections.Counter`, `from __future__ import annotations`; `match` statements |

The shim avoids every MicroPython gap that matters to Domino's own code. It stores State with `setattr`, walks `__bases__` for class names, caches per-class info, and detects whether a handler takes the event by calling it and retrying without the event on that exact `TypeError`. The rest is the component author's concern: the failing items above are what a client module can't use on MicroPython. Dict order only changes the order of attributes in the HTML, and morph doesn't care.

### Speed

Life step plus building the HTML string for an n×n board, in ms per frame:

| | 16×16 | 32×32 |
|---|---|---|
| CPython 3.13 (native) | 0.22 | 1.26 |
| Pyodide | 0.7–1.7 | 3.3–11.8 |
| MicroPython | 3.8–6.1 | 11.6–16.8 |
| Brython | 5.7–19.1 | 28.9–47.9 |

The real example is a 20×20 board, with 400 `<span>`s and a lambda per cell, rendered through the shim:

| | Python per generation (tick + render) | Morph | Generations/s (target 30) | Keystroke → DOM updated (TextStats) |
|---|---|---|---|---|
| CPython (the SSR path) | 0.12 + 1.37 ms | – | – | – |
| MicroPython | about 30 ms (tick 2–4 ms, render about 27 ms) | 2.8 ms | **26.7–27.7** | **1.7 ms** |
| Pyodide | about 10.6 ms | 2.9 ms | **30** | **0.4 ms** |
| Same component on the server (WebSocket, localhost) | – | – | – | 4.2 ms + real network RTT |

Before optimizing, the shim spent 53 ms per render on MicroPython. Caching class names and class attributes per class, collecting event types while binding, writing into one list, and fetching the HTML apart from the JSON answer brought that to about 27 ms. Most of the rest is MicroPython's cost per object and per attribute access: about 65 µs per element, where CPython takes about 3.5 µs.

### Why not a transpiler (for whole components)

Domino already has a restricted-subset checker: `domino/optimistic.py` decides which handlers can be precomputed. Applied to the 24 example components that have a `render()`, it accepts **10 of 36 handler methods**, and **0 of 6** in `Life` (loops, local variables, `list()`). Their `render()` methods use 41 kinds of AST node: lambdas, comprehensions, f-strings, `**kwargs`, attribute and method calls on arbitrary objects. They also call `len`, `str`, `enumerate`, `max`, `sum`, `round`, `range`, `reversed` and `type`. A transpiler that faithfully covers that much means reimplementing Python's semantics in JS: truthiness, integer division and modulo, string methods, `None` handling, closures over loop variables. That isn't a restricted subset any more. It's a Brython or Skulpt you'd have to maintain. Transpiling still makes sense for issue #23's Stage 2 (`@optimistic` handlers that only change State with plain expressions), where the subset is small and the server reconciles. It doesn't make sense for components that should work offline.

## Compatibility matrix

| Domino feature | Client component (MicroPython) | Notes |
|---|---|---|
| `State` per instance, `self.x += 1`, lists/dicts | ✅ | JSON values only (they're shipped in the HTML) |
| `render()` returning tags, lists, f-strings, `t.x()[...]`, `t.x()([...])` | ✅ | rendered without whitespace between tags |
| attributes: `class_`, `style` dicts, `aria_*`/`data_*`, `for_`, `True`/`False`/`None` | ✅ | same rules as the server |
| `on_<event>=` methods and lambdas, `event.value`/`form` | ✅ | plus `event.data`, `event.x`/`y`, `event.key`; `debounce=` is ignored |
| `after(ms, fn)` | ✅ | one pending timer per call site; the delay counts from the handler's start |
| class-level `css` | ✅ | written by the server, as for any component |
| `init()`, nested components, class attributes as HTML attributes | ✅ | nested components are recreated on each render, as on the server |
| SSR, works before the runtime loads, then hydrates | ✅ | |
| inside a server component; server re-render keeps it running | ✅ | matched by position and class |
| calling the server: `self.emit(name, value)` → parent's `on_<name>=` | ✅ | through the usual event channel |
| offline after load | ✅ | the open tab only (see open problems) |
| same code on Pyodide | ✅ | `client_python: "pyodide"` |
| `Collection`, `accounts`, `batch`, `refresh()`, `live = True` | ❌ | server-only; refused at startup |
| template strings `html(t"...")`, paired Jinja templates, `forms.Form` | ❌ | not in the shim yet |
| file uploads, `redirect()`, instant-update predictions | ❌ | not applicable or not implemented |
| `TestPage` (page tests) | SSR only | client handlers don't run there yet |

## Security

- **A client module is public.** The whole file is served to anyone who loads the page. Don't put secrets, server-only logic or private data in it. The import check stops the obvious mistakes, like `Collection`, `accounts`, `os` or your own server modules. It can't stop a literal secret written in the file.
- Only modules registered through a `client = True` class are served, by module name. Nothing else on disk can be fetched through `/_domino/client/module/`.
- `self.emit()` values come from the browser. The server handler must validate them like any form input. `Patterns.save` in the example does.
- The local runtime is pinned by version and sha512. The CDN default loads by version over HTTPS without Subresource Integrity, because `import()` and `loadMicroPython({url})` take no integrity option. Use `"local"` or your own URL if that matters to you.
- A strict CSP needs `'wasm-unsafe-eval'` (both runtimes) and the CDN's origin in `script-src` and `connect-src`.

## Open problems

1. **Data from the server after hydration.** The server re-rendering a parent with different props, such as `Life(pattern=...)`, doesn't reach a running island: morph keeps the island's DOM and its state. This needs a rule, such as "attributes win, State doesn't", or an explicit `self.receive()`.
2. **Island identity.** Islands are matched by position and class when the server re-renders around them, because each parent render creates a new instance with a new id. Reordering islands in a list would swap their states. Keys (`key=`) would fix this.
3. **Render cost.** Every change re-renders the whole island to an HTML string, and the browser morphs it. On MicroPython the string render dominates. An incremental approach would remove most of that: rendering to a JSON tree that a JS differ applies, or re-rendering only the child components whose State changed. MicroPython's GC also causes occasional frame-time spikes.
4. **Offline beyond the open tab.** Reloading offline fails, because neither the page nor the runtime is cached. A service worker that caches the runtime, loader, modules and the page shell would make this real offline support.
5. **JS interop.** Both runtimes have a `js` module (DOM, canvas, fetch), but the validator doesn't allow it yet. Allowing `import js` would make drawing on `<canvas>` easy (the drawing-pad use case). The cost is that components then only work in the browser and can't be server-rendered.
6. **Async handlers.** MicroPython (`runPythonAsync`) and Pyodide both support `async def`, but the shim calls handlers synchronously.
7. **Testing.** `TestPage` sees only the SSR. Since the shim runs in CPython, `TestPage` could run client handlers in-process too: same code, no browser.
8. **MicroPython quirks.** Component authors hit the gaps in the probe table (no `re.findall`, ASCII-only `lower()`, no `dataclasses`). A lint mode, or running the module under MicroPython (or a "MicroPython subset" AST check) at startup, would catch them before the browser does. Detecting whether a handler takes the event by retry is a hack.
9. **Runtime choice per component.** The setting is app-wide. A per-class `client = "pyodide"` would let a page mix a tiny MicroPython widget with one heavy Pyodide island.
10. **Pyodide's weight.** 5.3 MB and 3–6 s means Pyodide is for islands where the user expects to wait, like a data tool or a notebook. Memory snapshots aren't a browser feature yet.

## Recommendation

1. **Keep `client = True` as an experimental, opt-in island**, on MicroPython by default. It's worth it where latency or offline use is the whole point: text processing as you type, drawing, games and simulations, timers, editors and calculators. Keep islands under a few hundred elements per frame. The server remains the source of truth for data. Islands talk to it through `emit()`.
2. **Offer Pyodide as the "heavy island" switch**, as already implemented, for components that need real CPython or its packages. Don't use it for first-interaction UI.
3. **Don't build a whole-component transpiler.** Spend the compiler budget on issue #23's restricted `@optimistic` handlers instead. For latency compensation on server components they are the better tool, and they need no runtime.
4. **Before calling it stable:** add keys and a props-update rule (open problems 1–2), incremental rendering on MicroPython (3), a service worker for offline (4), `TestPage` running client handlers (7), and a MicroPython-subset check at startup (8).
