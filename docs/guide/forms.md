# Forms

Fields declared once, checked in the browser and on the server.

`domino.forms` builds a form from fields declared once. The browser checks them before anything is sent, the server checks them again on submit, errors appear next to each field, and your code gets typed values:

```python
from domino import forms

class Signup(forms.Form):

    name = forms.Text("Name", required=True, max_length=50)
    email = forms.Email("Email", required=True, live=True)
    age = forms.Integer("Age", min=13, max=120)
    plan = forms.Choice(["Hobby", "Pro", "Team"], default="Hobby")
    newsletter = forms.Checkbox("Send me news")
    password = forms.Password(required=True, min_length=8)
    confirm = forms.Password("Confirm password", required=True)

    submit_text = "Create account"

    def validate_email(self, email):                 # one field, on the server
        if users.find_one({"email": email}):
            return "That email is already registered."

    def validate(self, data):                        # across fields, once each is valid
        if data.password != data.confirm:
            raise forms.ValidationError("The passwords don't match.", field="confirm")

    def submitted(self, data):                       # only valid, typed data: data.age is an int or None
        users.insert({"name": data.name, "email": data.email, "age": data.age})
```

`Signup()` is a component that renders a `<form>`: a labelled input per field, in order, with its native constraints (`required`, `min`, `max`, `minlength`, `maxlength`, `pattern`, `type=email`), so the browser stops an invalid form without a round trip, and a submit button (busy while the submit is in flight, see [Loading and errors](events.md#loading-and-errors)).

- **Fields**: `Text`, `TextArea`, `Email`, `Password`, `Integer`, `Float`, `Date`, `Checkbox` and `Choice(choices)`. Values are typed: `int`, `float`, `datetime.date`, `bool`, the choice itself (choices can be `(value, label)` pairs, so `Choice([(1, "Small"), (2, "Large")])` gives an `int`); an empty field is `None` (`""` for text, `False` for a checkbox). Every field takes a label (default: the name, capitalized), `required`, `default`, `help` (text under the input), `validators`, `live`, `messages` and any HTML attribute for the input (`autocomplete="email"`, `placeholder=...`). `Text` and its kinds take `min_length`, `max_length` and `pattern` (matched against the whole value); `Integer`, `Float` and `Date` take `min` and `max`.
- **On submit** the server checks every field, whatever the browser did. With errors, each is shown under its field (`aria-invalid` and `aria-describedby` on the input, the message in a `role="alert"` element) and the form keeps what the user typed, except passwords, which aren't sent back to the page (`Password(keep=True)` changes that). Without errors `submitted(self, data)` is called with a `forms.Data` (a dict you can also read as `data.age`) and the form is reset to its initial values. In `submitted()`, `self.error("email", "Already taken")` rejects the submit after all: the error is shown and the values stay. `self.error(None, message)` shows a message above the form, and `self.reset()` clears it.
- **Custom checks**: `validators=[fn]` and `validate_<field>(self, value)` get the typed value of a field that isn't empty; `validate(self, data)` gets all of them once every field is valid. Any of them can return a message, raise `forms.ValidationError(message)` (with `field=` in `validate`) or call `self.error(...)`. Messages of the built-in checks can be changed per field: `forms.Text(required=True, messages={"required": "Who are you?"})`.
- **Live validation**: `live=True` checks a field on the server when its value changes (on leaving a text field), `live="blur"` whenever the user leaves it, and `live="input"` while they type, after `debounce=` ms (300 by default). It runs that field's checks only, through a normal event, and leaves the others alone.
- **Options**: `Signup(initial={"plan": "Pro"})` fills fields in (typed values, also what the form resets to), `Signup(submitted=callback)` hands the data to someone else (a parent showing a success view, say), and `Signup(submit_text="Join")` or the class attribute `submit_text` sets the button's text.
- **Layout**: fields are `<div class="field">` blocks, styled plainly by `Form`'s class-level `css` (scoped to `.Form`, so your own component's `css` or the page's styles win; `--form-accent` and `--form-error` set the colors). To lay a form out yourself, override `render()` and use `self.fields`: `self.fields.email.label()`, `.input(**attributes)`, `.help()`, `.error()`, or `.render()` for the whole block; `for field in self.fields` goes through them in order. The submit event stays bound whatever `render()` returns.
- **Without the component**: `Signup.validate_data(event.form)` returns `(data, errors)`, typed data and a dict of messages by field name, for any handler or route (`request.form` works too).

Field names can't be names a form already uses (`errors`, `fields`, `error`, `reset`, `render`, `id`, ...); declaring one raises an error. See `examples/forms/`.
