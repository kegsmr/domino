# Desktop apps

Run an app in a native window, and package it as a program with PyInstaller.

## In a window

A Domino app can be a desktop program: the server runs inside it, on the user's own machine, and a native window shows the app with the system's web engine (WebView2 on Windows, WebKit on macOS, Qt or GTK on Linux), through [pywebview](https://pywebview.flowrl.com/). Clicks don't wait on a network, and handlers can use the file system and any Python library. Install what it needs:

```
pip install domino-web[desktop]
```

That's pywebview and PyInstaller. On Linux, pywebview also needs Qt (`pip install PyQt6 PyQt6-WebEngine qtpy`) or GTK (from your distribution's packages).

While you work on it, run the app in a window instead of a browser tab:

```
domino desktop myapp
```

It's `domino run` in a window: hot reloading and the development MongoDB work as they do in a browser. Closing the window stops the server, and so does the window's program ending any other way (a crash, say).

## The main window

The window the pages are in is set by a `<window main>` tag in any of the app's templates (`windows/main.html`, say). It has options and no markup, since what it shows is the app's pages:

```html
<window main title="Notes" width="1024" height="768" min-width="480" min-height="320"></window>
```

Without one, the window is 1024 by 768, titled after the app's folder. Each window remembers its size when it's closed and opens at that size next time; on Windows and macOS it remembers where it was too (on Linux it opens centered, as X11 window managers report a window's place differently from how they place it). `domino desktop` keeps the sizes in the app's `.domino/windows.json`, a packaged program in the user's settings folder (`%APPDATA%\<name>`, `~/Library/Application Support/<name>`, `~/.config/<name>`). `remember="false"` turns it off for a window.

## More windows

A settings panel, an inspector, an about box: a window is a component shown in a window of its own, defined like one, in any `.html` file of the app (`windows/settings.html`, say):

```html
<window name="Settings" width="420" height="300" resizable="false">
    <h2>Settings</h2>
    <p>Section: {{ tab }}</p>
    <select on-change="pick(event)">...</select>
    <button on-click="close">Done</button>
</window>
```

```python
# windows/settings.py: optional, as for a component
from domino import Window

from data import theme


class Settings(Window):

    tab = "general"

    def pick(self, event):
        theme.value = event.value
```

- `<button open-window="Settings">` opens it when clicked. In a handler, `open_window("Settings", tab="audio")` (or `Settings.open(tab="audio")`) opens it with values: they're its values, like a component's attributes, and are sent through the browser, so they must be JSON.
- `close` (a `Window`'s method, there for windows without a class too), or `close_window()` in any handler, closes the window the event came from.
- A window is open once at a time: opening it again brings it to the front, with the new values if they changed.
- Windows are pages of their own, so each has its own `State`; what they share comes from a `Collection` or a module's `State`, and updates every window at once, as it updates every tab (above, the main window shows the theme Settings picks).
- `layout="Main"` puts a window in a layout, as for a page; otherwise it's a document of its own, titled with its `title`.
- Options, on `<window>` (and `<window main>`): `title` (default: its name), `width` and `height` (in pixels), `min-width` and `min-height`, `resizable`, `on-top`, `maximized` and `remember` (`true` or `false`).

In a browser (`domino run`, or a deployed app), a window is shown as a dialog on the page that opened it, at its size, with a title bar and a close button, so the same app works on the web too. See `examples/windows/`.

## Packaging

```
domino build --desktop myapp
```

This packages the app with PyInstaller into one program in `myapp/dist/`: `<name>.exe` on Windows, `<name>.app` on macOS, `<name>` on Linux, named after the main window's title. Users don't need Python. Build on each system you ship for, since PyInstaller doesn't cross-compile. On Windows and macOS the program uses the system's web engine; on Linux it carries Qt's, which makes it about 270 MB.

- The program holds the app's files (not its `_test.py` files), Domino, and the Python modules the app's files import. A module imported in an unusual way (`importlib`, say) needs an `import` somewhere in the app's files to be packaged.
- Its Tailwind CSS is built first, if it uses Tailwind.
- It serves without debug mode and without the development MongoDB. `Collection()` without a name keeps its data in memory while the program runs. Named collections need a MongoDB in the `mongo.url` setting; `domino build --desktop` warns when the app has them.
- Sessions last while the program runs, unless `settings.json` has a `secret_key`.

## Security

The server listens on `127.0.0.1` only, on a free port, and answers only its window. Each launch makes a random token; the window's first URL carries it, the server keeps it in a cookie (`HttpOnly`, `SameSite=Strict`) and sends the window on to the same URL without it. A request or WebSocket without the cookie is refused (`403`), so other programs, and web pages open in the user's browser, can't use the app, even though they can reach the port.
