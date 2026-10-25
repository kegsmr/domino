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
| `todo.py` | Form submits handled in Python with `event.form`, without reloading the page |
| `forms.py` | Form controls (`select`, range, checkbox), `event.value`, and re-rendering only part of a component |
| `bootstrap.py` | Layout built purely from Bootstrap grid and utility mixins (`col_4` renders as `col-4`) |
| `showcase.py` | A full landing page using the imperative style (`t.h1(parent, "text")`) and a contact form event |
