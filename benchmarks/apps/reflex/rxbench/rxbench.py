import reflex as rx

from rxbench.bench_hook import api
from rxbench.chat import ChatState, chat
from rxbench.counter import counter
from rxbench.todo import TodoState, todo


app = rx.App(api_transformer=api)
app.add_page(counter, route="/counter")
app.add_page(todo, route="/todo", on_load=TodoState.load)
app.add_page(chat, route="/chat", on_load=ChatState.join)
