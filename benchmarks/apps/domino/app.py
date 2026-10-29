from domino import Domino


# pages/counter.py, pages/todo.py and pages/chat.py are the three apps
app = Domino(__name__)


# --- benchmark hook (not counted as app code): the load generator posts chat messages here
from flask import request  # noqa: E402

from data import post  # noqa: E402


@app.route("/bench/chat", methods=["POST"])
def inject():

	post("bot", request.args["text"])

	return "ok"
