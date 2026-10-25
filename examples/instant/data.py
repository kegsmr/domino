from domino import Collection


# Kept in this process's memory, so the example runs without MongoDB; Collection("todos") would
# store them in MongoDB, and every open page would update the same way
todos = Collection()
messages = Collection()
