# Events and forms

Type a task and press Enter, tick it off, clear what's done: forms and events, handled in Python.

## Handling a form

Replace `components/tasks.py` with this version. Each task is now a dict that knows whether it's done:

{{ file: 2-events-and-forms/components/tasks.py }}

A few things are new:

- `on_submit=self.add` on the form runs `add` when it's submitted, without reloading the page. A handler that takes an argument receives the `Event`, and `event.form` holds the form's fields by name.
- After the submit, the form is reset to what the server rendered, so the text field is empty again, ready for the next task. While you type, Domino never overwrites what's in a field.
- `on_change=(self.toggle, index)` on each checkbox calls `self.toggle(index)` with that checkbox's own index: a handler and its arguments, as a tuple. A handler that also takes the event gets it after them.
- `required=True` is the browser's own check: an empty task isn't even sent.

{{ demo: 2-events-and-forms }}

## Lists in State

`self.items = self.items + [...]` assigns a new list rather than appending to the old one. Domino notices assignments, not changes inside a list, so building a new value (or assigning the same one again after changing it) is what re-renders the component.

## Instant, even on a slow connection

Some handlers don't need to wait for the server at all. When a handler only changes its own component's `State` with plain expressions, like a counter's `self.count += 1` or a menu's `self.open = not self.open`, Domino reads its code, works out ahead of time what the component will look like after it, and the browser shows that the moment you click; the server's answer then confirms it. The menu button of this site works that way on a phone.

The handlers here call other code (`dict()`, a list comprehension) or use what was typed, so they go to the server first, which on a normal connection takes a few milliseconds. See [Instant UI](/guide/instant-ui) for what qualifies.
