# Examples

Run any example from the repository root, then open http://127.0.0.1:5000:

```
python examples/counter.py
```

| Example | Shows |
|---|---|
| `hello_world.py` | A page built from tag classes, with an app-wide stylesheet served at `/style.css` |
| `functional.py` | Several pages linking to each other by passing view functions as `href` |
| `counter.py` | A component with state, re-rendered by `bind("click", ...)` |
| `random_number.py` | `after(ms, ...)` updating a component on a timer |
| `clock.py` | `refresh()` pushing a component to the browser from a background thread |
| `todo.py` | Form submits handled in Python with `event.form`, without reloading the page |
| `forms.py` | Form controls (`select`, range, checkbox), `event.value`, and re-rendering only part of a component |
| `search.py` | Search as you type: `bind("input", ..., debounce=250)`, with the input keeping focus and caret while results update |
| `attributes.py` | `class_` for extra CSS classes, `for_` for Python keywords, `aria_*`/`data_*` attributes and `style` dicts |
| `bootstrap.py` | Layout built purely from Bootstrap grid and utility mixins (`col_4` renders as `col-4`) |
| `showcase.py` | A full landing page using the imperative style (`t.h1(parent, "text")`) and a contact form event |
