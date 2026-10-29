# Components

Classes that render HTML, keep state and handle events.

A component is a Python class with its markup in HTML. **Markup lives in `.html` templates; Python is for logic and composition**: the class keeps the `State`, the helpers the template reads and the handlers its events call, and the template says what it looks like:

```python
# components/counter.py
from domino import State
import domino.tags as t


class Counter(t.div):

    count = State(0)  # each component has its own


    def increment(self):

        self.count += 1
```

```html
<!-- components/counter.html -->
<Counter>
    <p>Count: {{ count }}</p>
    <button on-click="increment">+</button>
</Counter>
```

Changing state re-renders the component, and only what changed is updated in the browser. A component that only decides *which* components to show writes that in Python, in `render()`, and passes them data and its own handlers:

```python
class Tasks(t.div):

    items = State([])


    def render(self):

        if not self.items:
            return [TaskForm(on_add=self.add), EmptyState()]

        return [TaskForm(on_add=self.add), TaskList(items=self.items)]
```

See [Templates](templates.md#templates) for the template syntax. Components can also be written entirely in Python, with tag classes, which suits small pieces and generated markup:

```python
from domino import Domino, State
import domino.tags as t


class Counter(t.div):

    count = State(0)  # each component has its own


    def render(self):

        return [
            t.p() [f"Count: {self.count}"],
            t.button(on_click=self.increment) ["+"],
        ]


    def increment(self):

        self.count += 1
```

- `on_<event>=handler` (`on_click`, `on_submit`, `on_input`, `on_change`, ...) runs `handler` on the server. Add `debounce=ms` to wait until the user pauses.
- A handler that returns nothing re-renders whatever its changes affected (or the component it belongs to); returning a component re-renders that one.
- `init(self)` runs once when the component is created, for setup that isn't state.
- The older style, `self([...])` with `element.bind("click", callback)` and `return self`, still works.

## Attributes

Keyword arguments become HTML attributes; underscores turn into hyphens (`aria_label` → `aria-label`, `data_user_id` → `data-user-id`). A trailing underscore avoids Python keywords (`for_` → `for`). `class_` (a string or list) adds CSS classes after the component's own, and `style` accepts a dict:

```python
t.button(class_="btn btn-primary", aria_pressed="false", style={"font_weight": "bold"})
```
