# Documentation

Domino's documentation, as markdown. The same pages make up the documentation website (`python website/app.py`).

## Tutorial

Build an app step by step:

1. [Your first page](tutorial/1-first-page.md)
2. [Events and forms](tutorial/2-events-and-forms.md)
3. [Styles](tutorial/3-styles.md)
4. [Pages and layouts](tutorial/4-pages-and-layouts.md)
5. [Reactive data](tutorial/5-reactive-data.md)
6. [Accounts](tutorial/6-accounts.md)
7. [Testing](tutorial/7-testing.md)
8. [Deploying](tutorial/8-deploying.md)

## Start

- [Installation](guide/installation.md): Install Domino and run the examples.

## Guide

- [Components](guide/components.md): Classes that render HTML, keep state and handle events.
- [State](guide/state.md): Values that re-render what shows them when they change.
- [Events](guide/events.md): Clicks, typing and submits, handled in Python on the server.
- [Developer tools](guide/devtools.md): Error pages, the component inspector and the event log, while debugging.
- [Styles](guide/styles.md): CSS on the component class, scoped to it and written once per page.
- [Tailwind CSS](guide/tailwind.md): Tailwind classes anywhere, with nothing to install or build.
- [Templates](guide/templates.md): Markup in HTML, logic in Python: Domino templates, Jinja and template strings.
- [Forms](guide/forms.md): Fields declared once, checked in the browser and on the server.
- [Pages & navigation](guide/pages.md): File-based routing, layouts, and page switches without reloading.
- [Reactive data & MongoDB](guide/reactive-data.md): Collections that re-render every open page when they change.
- [Server push](guide/server-push.md): Update open pages from anywhere, without waiting for an event.
- [Instant UI](guide/instant-ui.md): Clicks that show at once, even on a slow connection.
- [Client components](guide/client-components.md): Experimental: components that run in the browser, in Python.
- [Accounts](guide/accounts.md): Sign-up, login, password reset and email verification, with GitHub and Google.
- [Email](guide/email.md): Sending email, printed while debugging and captured in tests.
- [File uploads](guide/uploads.md): File inputs whose files arrive in your handler.

## Reference

- [Settings](guide/settings.md): settings.json, local overrides and environment variables.
- [Testing](guide/testing.md): Tests next to their page, in a simulated browser.
- [Deployment](guide/deployment.md): Deploy with one command, and serve on every CPU core.
- [Desktop apps](guide/desktop.md): Run an app in a native window, and package it as a program with PyInstaller.
- [Command line](guide/cli.md): domino create, run, serve, build, deploy and desktop.
- [How it works](guide/how-it-works.md): One WebSocket per tab, and the HTTP fallback.
- [Contributing](guide/contributing.md): Run Domino's own tests, publish a release, and the license.

## Research

- [Python in the browser](research/client-python.md): what client components can do, measured.
