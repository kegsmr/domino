# Instant UI

Clicks that show at once, even on a slow connection.

## Instant updates

Handlers that only change their component's own `State` with plain expressions — `self.count += 1`, `self.open = not self.open`, `if len(self.items) < 3: ...` — feel instant even on a slow connection, with nothing to configure. So do lambdas that only call such a method with plain values, like `on_click=lambda event, index=index: self.select(index)` (the method's parameters can be read like constants). Domino decides which handlers qualify by reading their code: anything that calls functions (like `messages.insert(...)`), uses the event's value, or touches anything but the component's `State` is never run ahead of time.

When the server renders such a component it follows those handlers from its current state to every state they lead to, renders each state once, and ships them inside the component (inert JSON) with which event leads to which state. Menus, tabs, accordions, toggles, a stepper with bounds or a carousel have only a few states, so the browser can show any number of clicks in a row the moment they happen, without waiting for the server even once. The events still go to the server, in order, and the server stays the source of truth: its answer to the last click in flight confirms what's shown, or puts it right if something changed on the server meanwhile (answers to earlier clicks don't undo later ones). If an event fails, the component goes back to what the server last showed. While the page shows something the server hasn't confirmed, the component has a `data-predicted` attribute.

A component whose states could go on forever (a counter) gets the states one click away instead, as do those with more than 16 states or more than 32 KB of HTML for them; set `optimistic_states = n` on the class to change the number. Set `optimistic = False` to turn it all off (each state costs a render on the server). See `examples/instant/`.

```python
class Tabs(t.div):

    active = State(0)

    def render(self):
        return [
            t.button(on_click=lambda event, index=index: self.select(index)) [name]
            for index, name in enumerate(["Overview", "How", "Truth"])
        ] + [t.p() [f"Tab {self.active}"]]

    def select(self, index):
        self.active = index
```

## Simulating a slow connection

Locally every click feels instant. To feel the app the way users on a slow connection will, run `Domino.enableLatencySim(300)` in the browser console: each round trip to the server then takes 300 ms (pushes are delayed too), for that tab, until `Domino.disableLatencySim()`. Or set it for the whole app while debugging with `{"domino": {"latency": 300}}` in `settings.json`; it's ignored when the app isn't in debug mode.
