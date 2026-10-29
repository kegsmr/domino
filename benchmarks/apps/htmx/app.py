"""Flask + htmx. htmx.min.js and the SSE extension are served from $BENCH_STATIC (copied from npm)."""

import os

from flask import Flask

import chat
import counter
import todo


app = Flask(__name__, static_folder=os.environ.get("BENCH_STATIC", "static"))
app.register_blueprint(counter.blueprint)
app.register_blueprint(todo.blueprint)
app.register_blueprint(chat.blueprint)
