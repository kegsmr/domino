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

It's `domino run` in a window: hot reloading and the development MongoDB work as they do in a browser. Closing the window stops the server. Settings for the window go in `settings.json`:

```json
{"desktop": {"title": "Notes", "width": 1024, "height": 768}}
```

The title defaults to the folder's name.

## Packaging

```
domino build --desktop myapp
```

This packages the app with PyInstaller into one program in `myapp/dist/`: `<name>.exe` on Windows, `<name>.app` on macOS, `<name>` on Linux, named after the window's title. Users don't need Python. Build on each system you ship for, since PyInstaller doesn't cross-compile.

- The program holds the app's files (not its `_test.py` files), Domino, and the Python modules the app's files import. A module imported in an unusual way (`importlib`, say) needs an `import` somewhere in the app's files to be packaged.
- Its Tailwind CSS is built first, if it uses Tailwind.
- It serves without debug mode and without the development MongoDB. `Collection()` without a name keeps its data in memory while the program runs. Named collections need a MongoDB in the `mongo.url` setting; `domino build --desktop` warns when the app has them.
- Sessions last while the program runs, unless `settings.json` has a `secret_key`.

## Security

The server listens on `127.0.0.1` only, on a free port, and answers only its window. Each launch makes a random token; the window's first URL carries it, the server keeps it in a cookie (`HttpOnly`, `SameSite=Strict`) and sends the window on to the same URL without it. A request or WebSocket without the cookie is refused (`403`), so other programs, and web pages open in the user's browser, can't use the app, even though they can reach the port.
