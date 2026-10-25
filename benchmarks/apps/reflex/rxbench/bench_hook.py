"""Not counted as app code: lets the load generator post chat messages to the shared room."""

from reflex.istate.manager.token import BaseStateToken
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route


async def inject(request):
	from rxbench.chat import ChatState, Message
	from rxbench.rxbench import app

	async with app.modify_state(BaseStateToken(ident="room", cls=ChatState)) as root:
		chat = await root.get_state(ChatState)
		chat.messages = [*chat.messages, Message("bot", request.query_params["text"])][-50:]
	return PlainTextResponse("ok")


api = Starlette(routes=[Route("/bench/chat", inject, methods=["POST"])])
