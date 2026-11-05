import itertools
import queue
import threading

from flask import Blueprint, Response, render_template, request


blueprint = Blueprint("chat", __name__)

# The last 50 messages, and a queue per open event stream
messages = []
listeners = set()
lock = threading.Lock()
ids = itertools.count()


def post(name, text):
	message = {"id": next(ids), "name": name, "text": text}
	html = render_template("message.html", message=message)
	with lock:
		messages.append(message)
		del messages[:-50]
		for listener in listeners:
			listener.put(html)


@blueprint.get("/chat")
def chat():
	return render_template("chat.html", messages=messages)


@blueprint.post("/chat")
def send():
	text = request.form.get("text", "").strip()
	if text:
		post("me", text[:500])
	return "", 204


@blueprint.get("/chat/stream")
def stream():
	listener = queue.Queue()
	with lock:
		listeners.add(listener)

	def events():
		try:
			while True:
				try:
					html = listener.get(timeout=15)
				except queue.Empty:
					yield ": keepalive\n\n"
					continue
				yield "event: message\ndata: " + html.replace("\n", "\ndata: ") + "\n\n"
		finally:
			with lock:
				listeners.discard(listener)

	return Response(events(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache"})


# --- benchmark hook (not counted as app code): the load generator posts chat messages here
@blueprint.post("/bench/chat")
def inject():
	post("bot", request.args["text"])
	return "ok"
