# Components

Classes that render HTML, keep state and handle events.

A component is a Python class with its markup in HTML. **Markup lives in `.html` templates; Python is for logic and composition**: the class keeps the `State`, the helpers the template reads and the handlers its events call, and the template says what it looks like:

```python
# components/counter.py
from domino import Component, State


class Counter(Component):

    count = State(0)  # each component has its own


    def increment(self):

        self.count += 1
```

```html
<!-- components/counter.html -->
<component name="Counter">
    <p>Count: {{ count }}</p>
    <button on-click="increment">+</button>
</component>
```

Changing state re-renders the component, and only what changed is updated in the browser. A component that only decides *which* components to show writes that in Python, in `render()`, and passes them data and its own handlers:

```python
class Tasks(Component):

    items = State([])


    def render(self):

        if not self.items:
            return [TaskForm(on_add=self.add), EmptyState()]

        return [TaskForm(on_add=self.add), TaskList(items=self.items)]
```

**Attributes are set by the parent; `State` is the component's own memory.** A class attribute (`items = []`, `on_add = None`) is a prop: `TaskList(items=found)` sets it, and other keyword arguments are HTML attributes. A misspelled prop holding a list, dict or object (`TaskList(itmes=found)`) gets a warning in debug mode, with the name it probably meant. A handler prop (`on_add = None`) is the parent's method, which the child calls (`self.on_add(text)`); the event then re-renders the parent.

`Component` renders as a `<div>`; `tag = "section"` on the class makes it another element (a template's `as="section"` must agree). Subclassing a tag, `class Card(t.article)`, works too.

See [Templates](templates.md#templates) for the template syntax. Components can also be written entirely in Python, with tag classes, which suits small or dynamic pieces and generated markup:

```python
from domino import Component, State
import domino.tags as t


class Counter(Component):

    count = State(0)  # each component has its own


    def render(self):

        return [
            t.p [f"Count: {self.count}"],
            t.button(on_click=self.increment) ["+"],
        ]


    def increment(self):

        self.count += 1
```

- A tag's children go in square brackets: `t.p ["text"]`, or `t.a(href="/") ["text"]` with attributes. Lists, tuples and generators in them are flattened and `None`/`False` skipped, so `t.ul [[t.li [item] for item in items]]` and `t.p ["Hi", user and t.b [user]]` work (a bare generator needs its own brackets: `t.ul [(t.li [x] for x in xs)]`). Numbers become text.
- `on_<event>=handler` (`on_click`, `on_submit`, `on_input`, `on_change`, ...) runs `handler` on the server. Add `debounce=ms` to wait until the user pauses.
- In a loop, give the handler its arguments as a tuple: `on_click=(self.remove, index)` calls `self.remove(index)`, and a handler that takes one more argument gets the event after them. (A `lambda` in a loop sees the loop variable's last value unless you write `index=index`.) Such handlers are [instant](instant-ui.md#instant-updates) like any other.
- `render()` returns the children; a handler that returns nothing re-renders whatever its changes affected (or the component it belongs to); returning a component re-renders that one.
- `init(self)` runs once when the component is created, for setup that isn't state. Events it binds (`self.configure(on_click=...)`) keep working after re-renders.
- Inline elements add no stray spaces: `t.p ["Built with ", t.a(href="/") ["Domino"], "."]` renders `<p>Built with <a href="/">Domino</a>.</p>`, while blocks stay one element per line.

### Older styles

They still work, most with a `DeprecationWarning`, for at least one more release:

| Older | Now |
|---|---|
| `self([children])` in `render()`, then `return self` | `return [children]` |
| `t.ul()([items])` | `t.ul [items]` |
| `t.h1(parent, "text")` (adds itself to `parent`) | `parent [t.h1 ["text"]]`, or return it from `render()` |
| `element.bind("click", handler)` | `on_click=handler` |
| `lambda event, i=i: self.remove(i)` | `on_click=(self.remove, i)` (lambdas aren't deprecated) |
| `live = True` for components that are `refresh()`ed | nothing (see [Server push](server-push.md#server-push)) |
| class attributes as HTML attributes (`role = "list"`, no longer rendered) | `attrs = {"role": "list"}` |
| `class X(t.div)` | `class X(Component)` (both work, no warning) |
| `from domino.components import Document`, `domino.core`, ... | `from domino import Document`; the other modules are internal now (see [Imports](#imports)) |

## Imports

`from domino import ...` has what apps use: `Domino`, `Component`, `Document`, `State`, `Collection`, `Event`, `redirect`, `batch`, `wait`, `html`, `template` and `TemplateError`, plus Flask's `request`, `session`, `g`, `abort` and `url_for`. The public modules are `domino.tags` (`import domino.tags as t`), `domino.accounts`, `domino.forms`, `domino.testing`, `domino.mail`, `domino.mongo` and `domino.bootstrap`. Everything else is internal, in modules whose names start with an underscore; the old paths (`domino.core`, `domino.components`, ...) work for one more release, with a `DeprecationWarning`.

## Attributes

Keyword arguments become HTML attributes; underscores turn into hyphens (`aria_label` → `aria-label`, `data_user_id` → `data-user-id`). A trailing underscore avoids Python keywords (`for_` → `for`). `class_` (a string or list) adds CSS classes after the component's own, and `style` accepts a dict:

```python
t.button(class_="btn btn-primary", aria_pressed="false", style={"font_weight": "bold"})
```

A component's class attributes are Python, never HTML: `placeholder = "What needs doing?"` is a setting the component uses, not `<div placeholder=...>`. HTML attributes its element always has go in `attrs`, which subclasses add to; keyword arguments and `configure()` win over them:

```python
class TaskList(Component):

    attrs = {"role": "list", "aria_label": "Tasks"}   # <div role="list" aria-label="Tasks">
    empty_text = "Nothing to do"                       # a setting (a prop), not an attribute
```

Before 0.4, a class attribute holding a string or number was also written on the element as an HTML attribute (`title = "Tasks"` gave every card a tooltip); move those that were meant as HTML attributes into `attrs`.
