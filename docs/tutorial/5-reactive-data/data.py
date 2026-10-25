from domino import Collection


# Shared by every page this server shows. Collection() without a name lives in memory;
# Collection("tasks") would keep the tasks in MongoDB
tasks = Collection()
