import itertools

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


router = APIRouter(prefix="/api/todos")

# In memory, shared by every tab of this server process
todos = {number: {"id": number, "text": f"Todo item {number}", "done": False} for number in range(1000)}
ids = itertools.count(1000)


class NewTodo(BaseModel):
	text: str


class TodoChange(BaseModel):
	done: bool


@router.get("")
def list_todos():
	return list(todos.values())


@router.post("")
def add_todo(todo: NewTodo):
	item = {"id": next(ids), "text": todo.text, "done": False}
	todos[item["id"]] = item
	return item


@router.patch("/{id}")
def change_todo(id: int, change: TodoChange):
	if id not in todos:
		raise HTTPException(404)
	todos[id]["done"] = change.done
	return todos[id]
