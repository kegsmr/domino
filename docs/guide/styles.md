# Styles

CSS on the component class, scoped to it and written once per page.

A component declares its styles on the class, with `css`. They are scoped to its class name and written into the page's `<head>` once, however many times the component is shown:

```python
class Card(t.div):

    css = {
        "padding": "1rem",                              # .Card
        "background": "var(--surface)",
        "h3": {"margin": 0},                            # .Card h3
        ":hover": {"box_shadow": "0 2px 8px #0002"},    # .Card:hover
        "& + &": {"margin_top": "1rem"},                # .Card + .Card
        "@media (max-width: 600px)": {"padding": ".5rem"},
    }
```

- Property names are written with underscores (`font_size`); `__accent` (or `"--accent"`) is the CSS variable `--accent`. Values are written as given (no units are added), and `None` leaves a property out.
- A nested key is a selector. Keys starting with `:` or `[` (`":focus"`, `"::after"`, `"[open]"`) attach to the enclosing selector, other keys (`"h3"`, `"> li"`, `"input, textarea"`) select descendants, and `&` stands for the enclosing selector anywhere (`"&.active"`, `"& + &"`). `""` is the component itself.
- `@media`, `@supports`, `@container` and `@layer` blocks hold the same kind of rules; other at-rules, such as `@keyframes` and `@font-face`, are written as they are, unscoped.
- `css` can also be plain CSS, scoped the same way: `css = "& { padding: 1rem } h3 { margin: 0 }"`.
- Subclasses keep their base class's styles (the element has both classes) and add their own, which come later and so win.
- When a component first appears in an event response or a push, its CSS comes with it and is added to the page once.

A page's own rules go on the `Document`, and can be added at any point, including from a component's `render()`, since the page's CSS is computed when it has finished rendering:

```python
page.style("body", font_family="system-ui", margin="2rem auto")
page.style("a", {":hover": {"color": "red"}, "@media print": {"color": "black"}})  # nested, as in css
page.theme(surface="#fff", text="#111", dark={"surface": "#111", "text": "#eee"})  # --surface, --text
```

`theme()` sets CSS variables on `:root`, with the `dark` values for visitors whose system prefers a dark color scheme. Component CSS comes before the page's in the `<head>`, so where both match equally the page wins.

Styles shared by every page can go in a stylesheet the browser caches: `stylesheet = app.style("/style.css")` serves it, `stylesheet.style(...)` adds rules to it (the same as `page.style`), and `stylesheet.link(head)` links it from a page. For a single element, use the `style` attribute (a dict, see Attributes). `stylesheet.style(element, ...)` still works too, but writes a `<style>` block for each element it's used on; for a component shown many times, `css` is much smaller.

CSS can't close the `<style>` element it's written in, whatever the values hold. See `examples/styles/`.
