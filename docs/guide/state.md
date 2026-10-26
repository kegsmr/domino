# State

Values that re-render what shows them when they change.

`State(value)` holds a value the page shows. Reading it in `render()` subscribes the component, and changing it re-renders every component that read it:

- As a class attribute (`count = State(0)`), each component instance has its own value; read and assign it as `self.count`.
- At module level (`online = State(0)`), one value is shared by everyone: `online.value` reads it and `online.value = 3` changes it, re-rendering the components that show it on every open page (see [Reactive data](reactive-data.md#reactive-data)).
- Lists and dicts: assign a new value (`self.items = self.items + [x]`) or set them again after changing them in place, since changes inside them can't be seen.
- Each page load, including a page swapped in by a link, makes its components afresh, so their state starts again. Keep what should last, or be shared, in a `Collection`.
- Handlers that only change their own component's `State` show at once in the browser, before the server answers (see [Instant updates](instant-ui.md#instant-updates)).
