import itertools

from flask import Blueprint, render_template, request


blueprint = Blueprint("todo", __name__)

# In memory, shared by every tab of this server process
todos = {number: {"id": number, "text": f"Todo item {number}", "done": False} for number in range(1000)}
ids = itertools.count(1000)


def summary():
	return f"{sum(item['done'] for item in todos.values())} of {len(todos)} done"


@blueprint.get("/todo")
def todo():
	return render_template("todo.html", todos=todos.values(), summary=summary())


@blueprint.post("/todo")
def add():
	text = request.form.get("text", "").strip()
	if not text:
		return "", 204
	item = {"id": next(ids), "text": text, "done": False}
	todos[item["id"]] = item
	return render_template("todo_changed.html", item=item, summary=summary())


@blueprint.post("/todo/<int:id>/toggle")
def toggle(id):
	todos[id]["done"] = not todos[id]["done"]
	return render_template("todo_changed.html", item=todos[id], summary=summary())
