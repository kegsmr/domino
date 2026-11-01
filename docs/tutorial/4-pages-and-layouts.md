# Pages and layouts

A second page, and a layout that puts the navigation and the theme around every page.

## A layout

`pages/layout.py` wraps every page in its folder and below. Its `layout(content)` gets what a page returned and returns the whole document. Move the `Document` and the theme from `pages/index.py` into it, and add a navigation:

{{ file: 4-pages-and-layouts/pages/layout.py }}

`request` is Flask's: the layout runs while the page is being requested, so `request.path` is the page's path, and `aria-current="page"` marks its link. Domino is built on Flask, so Flask's `request`, `session`, `abort` and `redirect` all work as usual.

## Pages return their content

`pages/index.py` now returns just what's on it:

{{ file: 4-pages-and-layouts/pages/index.py }}

And a second page, `pages/about.py`, is the page at `/about`:

{{ file: 4-pages-and-layouts/pages/about.py }}

`components/tasks.py` stays as it was in step 3.

## Moving between pages

Click between Tasks and About: the page doesn't reload. Domino fetches the next page, swaps it in, keeping what stays the same (the navigation), and adds it to the history so back and forward work. There's nothing to set up and no client-side router; this docs site works the same way.

More page files work the same: `pages/users/[id].py` is `/users/<id>`, its `page(id)` gets the id, and `pages/404.py` is shown for URLs no page serves. See [Pages & navigation](../guide/pages.md).
