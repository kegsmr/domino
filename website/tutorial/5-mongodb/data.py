from domino import Collection


# The "tasks" collection in MongoDB: kept across restarts, and shared by every server process.
# `domino run` starts a MongoDB for you while you develop
tasks = Collection("tasks")
