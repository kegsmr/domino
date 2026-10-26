# Accounts

Sign-up, login and logout, so tasks say who added them and only members can change the list.

## Login and sign-up pages

`domino.accounts` keeps users in the `users` collection in MongoDB, next to the tasks, and comes with the forms. Two pages show them:

{{ file: 6-accounts/pages/login.py }}

{{ file: 6-accounts/pages/signup.py }}

The forms check what's typed, show errors next to the fields, and after logging in go to the `?next=` address, if there is one.

## Who's signed in

`accounts.UserMenu()` shows "Signed in as …" with a Log out button, or Log in and Sign up links. Put it in the layout's navigation:

{{ file: 6-accounts/pages/layout.py }}

## Tasks by members

`accounts.current_user()` is the signed-in user's document, or `None`. It's reactive like a collection: a component that reads it in `render()` re-renders when the user logs in or out on that page, so the form appears as soon as you've signed in:

{{ file: 6-accounts/components/tasks.py }}

The handlers check the user again. They run on the server, with the page's own record of who's signed in, so the browser can't claim to be someone else.

{{ file: 6-accounts/data.py }}

## Run it

Accounts keep the signed-in user in Flask's session cookie, which is signed with the app's `secret_key` setting. While you develop, `domino run` makes one up (so logins last until a restart); in production you set your own, as step 8 shows.

```bash
domino run tasks
```

Sign up, add a task, and open a private window: it sees the task, with your name next to it, but can't add one until it signs in. GitHub and Google sign-in take a few lines of settings; see [Accounts](../guide/accounts.md).
