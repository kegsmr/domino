import time

from domino import Collection


# The chat's messages: in memory, shared by every tab of this server process
messages = Collection()


def post(name, text):

	messages.insert({"name": name, "text": text, "sent": time.time()})
