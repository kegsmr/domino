from nicegui import app

import chat


@app.post("/bench/chat")
def inject(text: str):
	chat.post("bot", text)
	return "ok"
