import itertools

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


router = APIRouter()

# The last 50 messages, and every open socket
messages = []
sockets = set()
ids = itertools.count()


async def post(name, text):
	message = {"id": next(ids), "name": name, "text": text}
	messages.append(message)
	del messages[:-50]
	for socket in list(sockets):
		try:
			await socket.send_json({"message": message})
		except Exception:
			sockets.discard(socket)


@router.websocket("/api/chat")
async def chat(socket: WebSocket):
	await socket.accept()
	await socket.send_json({"history": messages})
	sockets.add(socket)
	try:
		while True:
			data = await socket.receive_json()
			await post(str(data["name"])[:30], str(data["text"])[:500])
	except WebSocketDisconnect:
		sockets.discard(socket)


# --- benchmark hook (not counted as app code): the load generator posts chat messages here
@router.post("/bench/chat", include_in_schema=False)
async def inject(text: str):
	await post("bot", text)
	return "ok"
