import os

from nicegui import ui

import bench_hook  # noqa: F401  (not counted as app code: lets the load generator post chat messages)
import chat  # noqa: F401  (each module adds its page: /chat, /counter, /todo)
import counter  # noqa: F401
import todo  # noqa: F401


ui.run(host="127.0.0.1", port=int(os.environ["PORT"]), reload=False, show=False)
