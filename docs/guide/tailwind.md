# Tailwind CSS

Tailwind classes anywhere, with nothing to install or build.

Turn it on with one setting, and write [Tailwind](https://tailwindcss.com) classes anywhere: on tag classes, in Jinja templates, in template strings. There's no Node, npm, config file or build step:

```json
{"tailwind": true}
```

```python
t.div(class_="rounded-xl bg-white p-6 shadow-sm dark:bg-slate-900") [
    t.h2(class_="text-lg font-semibold") ["Hello"]
]
```

- **Turning it on**: `"tailwind": true` in `settings.json` (or `DOMINO_TAILWIND=true`), or a `tailwind.css` file in the app's folder. `"tailwind": false` turns it off even then. `domino create myapp --tailwind` makes an app styled with it.
- **How it works**: Tailwind's official standalone CLI (Tailwind v4, one executable) is downloaded the first time from its GitHub releases, for your OS and CPU, checked against the release's SHA-256 sums, and kept in `~/.domino/tailwind/<version>/` (or under `DOMINO_HOME`), so later runs work offline. It reads the app's `.py` and `.html` files (skipping `.domino/` and anything `.gitignore` lists) for class names, and writes the CSS for those it finds, and only those, to `.domino/tailwind.css`. Every page links it in its `<head>`, at `/_domino/tailwind.css?v=<hash of the CSS>`: `Document` pages, pages with a `t.head` of their own, and Jinja pages.
- **While debugging** (`domino run`, `app.run(debug=True)`), it's built once at startup, then the CLI keeps running, watching the app's files, and rebuilds when one changes. Open pages hear about it and swap in the new stylesheet without reloading, so a class added in a template shows up as you save it (a `.py` file restarts the server; the CSS is rebuilt meanwhile). The CLI stops with the server, however it stops. Errors in your CSS are printed and the server keeps going.
- **Version**: Tailwind 4.3.3 by default; `{"tailwind": {"version": "4.1.0"}}` picks another release.
- **Offline, or an OS without a build**: if the download fails, the error says so, and pages work without the CSS. Download the CLI for your platform from [Tailwind's releases](https://github.com/tailwindlabs/tailwindcss/releases) yourself and set `DOMINO_TAILWIND_BIN` to its path (or save it where the message says).

## Your own theme

Tailwind v4 is configured in CSS. Without a `tailwind.css`, Domino makes one in `.domino/` that imports Tailwind and points it at the app's files. To customize it, put a `tailwind.css` in the app's folder (or name another file with `{"tailwind": {"input": "styles/app.css"}}`); it's used as it is:

```css
@import "tailwindcss";
@source not ".domino";      /* unless .gitignore lists .domino/ */

@theme {
    --color-brand: #ff6a00;
    --font-display: "Inter", sans-serif;
}
```

`bg-brand` and `font-display` then work like any other class. Tailwind finds classes in the app's folder (the CLI runs there), skipping what `.gitignore` lists; `@source "../shared";` adds a folder.

## Tailwind in production

`domino serve` (and `app.run()` without debug mode) builds minified CSS once at startup, before the workers start, and never watches. If the CLI isn't downloaded but a `.domino/tailwind.css` is there, that one is served, so an image built with the CSS needs no download when it starts. The CSS is served with `Cache-Control: public, max-age=31536000, immutable` at its hashed URL, so browsers download it again only when it changes. Servers that didn't build it (`uvicorn app:app.asgi`, `gunicorn app:app`, `flask run`) build it on the first request for it, if the CLI is already downloaded (or, in debug mode, after downloading it).

`domino tailwind build [folder]` builds the minified CSS into `.domino/tailwind.css` (downloading the CLI if needed): the step to run when building a deploy, e.g. in a Dockerfile, after copying the app in:

```dockerfile
RUN domino tailwind build
```

## Caveats

- Class names must appear in full somewhere in the app's files: Tailwind reads the source, it doesn't run it. `class_="bg-red-500" if error else "bg-green-500"` works; `f"bg-{color}-500"` doesn't, unless each full name is written somewhere (a dict of names, say).
- Tailwind's CSS is all in cascade layers, and CSS outside a layer beats CSS in one, so a component's `css` and `page.style()` rules win over utilities that set the same property. Put the component's rules in a layer (`css = {"@layer components": {...}}`) to let utilities override them, or use Tailwind's `!` (`p-8!`).
- Two utilities for the same property on one element (`text-slate-600 text-indigo-600`) leave the winner to the order of Tailwind's CSS, not of the classes: add one or the other.
- Tailwind's base styles (Preflight) reset margins, headings and buttons on every page of the app.
