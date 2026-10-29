# Templates

Markup in HTML, logic in Python: Domino templates, Jinja and template strings.

Domino templates are plain HTML with three additions: components are capitalized tags, lists and conditions are blocks in Python's words (`{{ for task in tasks }}` ... `{{ /for }}`), and every value comes from Python. There's no other logic in them: anything more than a name, an attribute or a helper call is a helper method in Python. See `examples/templating/`.

```html
<!-- components/todos.html -->
<component name="TodoList" class="todos">
    <ul>
        {{ for index, item in enumerate(items) }}
        <li class="{{ item_class(item) }}">
            <input type="checkbox" checked="{{ item.done }}" on-change="toggle(index)">
            {{ item.text }}
            <button on-click="remove(index)" aria-label="Remove">×</button>
        </li>
        {{ else }}
        <li>Nothing to do!</li>
        {{ /for }}
    </ul>
    {{ if remaining }}
    <p>{{ remaining }} left</p>
    {{ else }}
    <p>All done.</p>
    {{ /if }}
    <Card heading="Tips"><p>Click an item to finish it.</p></Card>
</component>
```

```python
# components/todos.py
class TodoList(t.div):

    items = State([])


    def remaining(self):                     # a helper: {{ remaining }} calls it

        return sum(1 for item in self.items if not item["done"])


    def item_class(self, item):              # in class, a string, a list or {class: bool}

        return {"done": item["done"]}


    def toggle(self, index):

        ...


    def remove(self, index):

        self.items = self.items[:index] + self.items[index + 1:]
```

**Defining a component.** `<component name="TodoList">...</component>` holds the markup of the component of that class (the class still makes the outer element, here a `<div>`). Every file says what it holds: `<component>` definitions, a `<layout>` or a `<page>`; lowercase tags define, capitalized tags use. Attributes on `<component>` go on the component's element, after what the Python side sets (`class` adds up, other attributes the Python side set win); `as="aside"` makes the element an `<aside>` instead (a class that sets its own `tag` must agree). A file can define several components, and holds nothing but definitions.

**Where they go.** Put them anywhere in the app; by convention next to the module, with the same name (`todos.py` and `todos.html`). Domino reads every `.html` file of the app's folder at startup (skipping hidden folders, `node_modules`, `site-packages` and `static/`, and pages and Jinja templates) and finds each component's definition by its name. Two definitions of one name stop the app at startup, naming both files, unless two classes of that name in different modules each have theirs next to their module, which then wins. A definition no class is named after is a warning. A class with a `render()` uses that instead.

**Using components.** A capitalized tag shows a component: `<Counter />`, or `<Card heading="Tips">children</Card>`. They're live like any other: events, `State`, re-renders and instant updates work. Classes are found by name: in the module of the component whose template it is (or, for `template()`, its context and the calling module), then among the app's component classes; one not imported yet is imported from the module next to a file that defines components (or `components/<snake_case name>.py`). An unknown name is an error with the closest names.

- Attributes become what the component declares: a `State` (its starting value), a property with a setter, or a class attribute (`heading = ""`). Plain attributes are strings; `items="{{ visible }}"` passes the value itself. Other attributes (`class`, `id`, `aria-*`, ...) go on its element, as in Python.
- `on-add="add"` passes a handler: if the component declares `on_add = None`, the handler is its prop, which it calls itself (`self.on_add(text)`), and the event then re-renders the parent; otherwise it's a DOM event on the component's element.
- What's between `<Card>` and `</Card>` goes where Card's template has `<slot />` (`<slot>fallback</slot>` shows its own content when there's none). Python composition works the same way: `Card(heading="Tips") [t.p() ["..."]]`.

**Values.** `{{ name }}`, `{{ item.text }}` and `{{ item["text"] }}` read the component's `State`, properties, attributes and helper methods (called without arguments: helpers are how logic stays in Python), and loop variables. `.name` also reads a dict's key, and a missing key is nothing; an unknown name, or an object's unknown attribute, is an error naming the template's file, line and column, with the names that exist. `helper(item, "text")` calls a method with values; `not x` is the one operator. Nothing else: no comparisons, arithmetic or filters, so write a helper (`is_open(index)`, `remaining`).

**Functions outside the class.** A helper that keeps no state doesn't need to be in a class: the functions defined at the top level of the component's module (and of the `.py` file next to its template) are read like its methods, after the component's own names. A component with no class can have them too, with only functions in its `.py` file:

```python
# components/price.py
def money(cents):
    return f"${cents / 100:.2f}"
```

```html
<!-- components/price.html -->
<component name="Price">
    <b>{{ money(amount) }}</b>
</component>
```

They can handle events as well (`on-click="vote"`, with `vote()` adding to a `Collection`). Functions the module imports, and those whose names start with `_`, aren't read. A class is only needed for what a component remembers: its `State`.

- Text is escaped; `Markup` values and Domino elements are inserted as they are; `None` and `False` show nothing. In `<script>` values are inserted as JSON.
- In attributes too (`aria-*` and `data-*` attributes write `true` or `false`): `href="/polls/{{ poll.id }}"`, `class="task {{ if task.done }}done{{ /if }}"` (an `{{ if }}` block works inside an attribute).

**Lists and conditions** are blocks, in Python's words and closed like HTML: `{{ for item in items }}` ... `{{ /for }}` repeats what's inside (`{{ for key, value in prices.items }}` unpacks, `enumerate(items)` numbers), and `{{ if done }}` ... `{{ elif loading }}` ... `{{ else }}` ... `{{ /if }}` shows one part (`{{ if not items }}` too). `{{ else }}` inside a `for` shows when the list is empty. A block wraps whole elements: one that starts inside an element ends inside it, so `{{ if x }}<div>{{ /if }}` is an error at startup, with the file and line. A block on a line of its own takes the line with it.

**Attributes** are written as they are, with any `{{ }}` values in them filled in and escaped. An attribute that is just one value can switch it on and off: `disabled="{{ at_zero }}"` writes `disabled` when the value is true and leaves it out when it's false or None, and on a component, `items="{{ items }}"` passes the list itself. In `class`, a list or a dict `{class: bool}` gives the names that are on (`class="task {{ row_class(task) }}"`); in `style`, a dict gives declarations (`{"font_weight": "bold"}`).

**Events**: `on-click="increment"` binds a method; `on-click="remove(index)"` binds it with values, so each item of a list gets its own. `on-input="search(event)"` passes the `Event`; `debounce="250"` waits until the user pauses; `while-pressed` makes hover events (`on-pointerenter`, `on-pointerover`, `on-mouseenter`, ...) count only while a mouse button is held down, for painting or selecting by dragging (see `examples/pixels`). Handlers that only change the component's own `State` are [instant](instant-ui.md#instant-updates), with values too.

**Whitespace** is kept as written: nothing is added around inline elements (`<a>Domino</a>.` has no space before the dot), and a block's own lines leave nothing behind, so each item is on a line of its own and a hidden element leaves no empty line.

**Pages and layouts.** An `.html` file in `pages/` without a `.py` of the same name is a page: `pages/about.html` is `/about`, with the URL's parameters as its values (`pages/users/[name].html` reads `{{ name }}`). Its markup is inside `<page>...</page>`, and `<page layout="Main" title="About">` puts it in a layout (see [Pages](pages.md#pages)). A page with `<html>`, or `<head>` and `<body>` without `<html>`, is a whole document itself, used without layouts. Domino adds the doctype, its script and the components' CSS to documents. `template("home.html", title="Home")` renders any template from Python.

**Compiled once.** Each file is parsed once into static HTML strings and the few dynamic parts, so rendering a template does little more than join strings (about as fast as Jinja, faster than tag classes); while debugging, a file that changed is parsed again, and hot reloading updates open pages.

## Jinja or Domino?

Jinja stays available, for pages and existing templates. A file is Jinja when it starts with `{# jinja #}`, ends in `.jinja`, or uses anything only Jinja has (`{% %}`, `{# #}`, filters, operators, Jinja's globals such as `url_for`, `component`, `on`); `{"templates": "jinja"}` in the settings reads every page template as Jinja, and `{# domino #}` at the top marks a Domino one. Files of `<component>`, `<layout>` or `<page>` are always Domino templates.

## Template strings (Python 3.14)

`html()` turns a [template string](https://peps.python.org/pep-0750/) (`t"..."`) into the same Domino elements tag classes make, so events, `State`, escaping, instant updates and in-place patching all work as before:

```python
from domino import State, html
import domino.tags as t


class Counter(t.div):

    count = State(0)
    items = State(["a", "b"])


    def render(self):

        return html(t"""
            <p>Count: {self.count}</p>
            <button on_click={self.increment}>+</button>
            <ul>{[html(t"<li>{item}</li>") for item in self.items]}</ul>
        """)


    def increment(self):

        self.count += 1
```

- As text, `{value}` is escaped; an element, or a list of elements and text, becomes children; `None` and `False` render nothing; `Markup` is inserted as it is. Inside `<script>` values are inserted as JSON.
- As an attribute value (`name={value}`, quoted or not), the value is passed like a keyword argument: `on_click={self.increment}` binds the event (`debounce=250` applies), `class={["a", "b"]}`, `style={styles}` with a dict, and `True`/`False`/`None` follow the usual attribute rules. Attribute names are the keyword names with hyphens allowed: `aria-label`, `data-id`, `for`, `class`.
- `<div {attributes}>` spreads a dict of attributes.
- `<{Card} title="x">children</{Card}>` or `<{Card} />` creates a component, with the attributes as keyword arguments.
- Tags are the classes in `domino.tags` (`<div>` is `t.div`); other names, like `<my-widget>`, make a plain element with that tag.
- One root element returns that element; otherwise `html()` returns a list, which works as `render()`'s result and as children.
- Each template is parsed once (cached by its static text), so rendering one only fills in the values. Invalid HTML, such as an unclosed or mismatched tag, raises `TemplateError` with the line number.
- Use `{{` and `}}` for literal braces, as in f-strings. Lambdas need parentheses: `on_change={(lambda: self.remove(index))}`.

Template strings need Python 3.14; on older versions `html()` raises an error saying so (the rest of Domino works from 3.9).

## Jinja templates

Flask's Jinja templates suit layouts and mostly static pages. Domino finds `.html` templates by file name anywhere in the app's folder: `templates/` as in Flask, or next to the code that uses them. Hidden folders, `.domino/`, `static/`, `node_modules/`, `__pycache__/`, virtualenvs and folders with an `app.py` of their own (other apps) are skipped. Since names are looked up without folders, two templates with the same name stop the app at startup with both paths. While debugging, edited and new templates are picked up without a restart.

`template(name, **context)` renders one as an element; return it from a page's `page()` (or a route) to make it the whole page (Domino adds its script, its page id and the CSS of the components inside), or use it as a child. Inside, `{{ component(Counter) }}` (or `{{ component(Counter, title="x") }}`) and `{{ element }}` render live Domino components, whose events and re-renders work as usual; the Jinja part around them is static.

```python
# pages/index.py
def page():

    return template("home.html", title="Home", Counter=Counter)
```

```html
<body>
    <h1>{{ title }}</h1>
    {{ component(Counter) }}
</body>
```

Components can have Jinja templates too, the older way: a component without a `render()` or a Domino definition, whose module has a template next to it named after the class (`TodoList` → `todo_list.html`) or after the module (`counter.py` → `counter.html`), its markup not inside a `<TodoList>` tag, renders that template with Jinja. Its `State` values and methods are available by name, and the component itself as `this` (Jinja keeps `self` for its blocks). `on(click=handler)` binds events, like `on_click=`; it takes several events and `debounce=`. Reading `State` subscribes the component and its handlers are predicted for instant updates, as with `render()`. A `render()` method, when there is one, wins over the template.

```python
# components/counter.py
class Counter(t.div):

    count = State(0)


    def increment(self):

        self.count += 1
```

```html
<!-- components/counter.html -->
<p>Count: {{ count }}</p>
<button {{ on(click=increment) }}>+1</button>
```

Domino templates are the recommended way to write markup; Jinja suits existing templates and pages that need its logic, template strings small pieces of markup inside Python.
