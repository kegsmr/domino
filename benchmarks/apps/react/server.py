"""The JSON API and static files for the React app (src/, bundled into $BENCH_BUILD by esbuild)."""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import api_chat
import api_todo


BUILD = Path(os.environ.get("BENCH_BUILD", Path(__file__).parent / "build"))

app = FastAPI()
app.add_middleware(GZipMiddleware, minimum_size=500)
app.include_router(api_todo.router)
app.include_router(api_chat.router)
app.mount("/assets", StaticFiles(directory=BUILD), name="assets")


@app.get("/{path:path}")
def index(path: str):
	return FileResponse(BUILD / "index.html")
