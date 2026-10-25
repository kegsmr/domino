# Styles

Give the component its own CSS, right on the class, and the page a theme with a dark variant.

## CSS on the component

Add a `css` attribute to `Tasks`. It's written like CSS, as a dict: property names with underscores, nested keys for selectors inside the component:

{{ file: 3-styles/components/tasks.py }}

Domino scopes these rules to the component's class name. `"li"` becomes `.Tasks li`, `"input[name=text]"` becomes `.Tasks input[name=text]`, and plain properties at the top (`max_width`) style the component itself. The CSS goes into the page's `<head>` once, however many `Tasks` the page shows, and when a component first appears in an event's response its CSS comes along with it.

Keys starting with `:` attach to the selector around them (`":hover"`), `&` stands for it (`"& + &"`), and `@media` blocks hold the same kind of rules. The [Styles](/guide/styles) guide has the details.

## A theme

The colors are CSS variables. The page sets them with `page.theme()`, and the values in `dark` apply when the visitor's system prefers a dark color scheme. To set it, the page now returns a whole `Document`, which is the `<html>` element, with its `<head>` and `<body>`:

{{ file: 3-styles/pages/index.py }}

`page.style()` adds rules for the whole page. Component CSS comes first in the `<head>`, so where a page rule and a component rule match equally, the page wins.

The demo below is the step's component; it gets its colors from this site's theme, which uses the same variable names. Switch this site to dark mode (top right) and it follows.

{{ demo: 3-styles }}
