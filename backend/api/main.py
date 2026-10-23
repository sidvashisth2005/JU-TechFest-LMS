"""LMS API: REST for the dashboard, a live WebSocket, the rover proxy, and the built web app.

python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
"""

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend.api import auth, db, public, routes, rover
from backend.config import CHANNEL_LIVE, ROOT, settings

log = logging.getLogger("api")


class RedactTokens(logging.Filter):
    """The video stream and WebSocket pass the login token as ?token=...; keep it out of logs."""

    pattern = re.compile(r"token=[^&\s\"]+")

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.args = tuple(self.pattern.sub("token=***", a) if isinstance(a, str) else a for a in record.args)
        record.msg = self.pattern.sub("token=***", str(record.msg))
        return True


for _name in ("uvicorn.access", "uvicorn.error"):
    logging.getLogger(_name).addFilter(RedactTokens())
WEB_DIST = ROOT / "web" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.pool.open(wait=False)
    yield
    db.pool.close()


app = FastAPI(title="LMS API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    # the Vite dev server; in production the web app is served from this same origin
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(routes.router)
app.include_router(rover.router)
app.include_router(public.router)


@app.get("/api/health")
def health() -> dict:
    try:
        db.one("SELECT 1")
        database = "ok"
    except Exception as e:  # health must answer even when the DB is down
        database = f"error: {type(e).__name__}"
    return {"status": "ok", "database": database}


@app.websocket("/ws/live")
async def live(ws: WebSocket, token: str = ""):
    try:
        auth.verify(token)
    except Exception:
        await ws.close(code=4401)
        return
    await ws.accept()
    r = aioredis.from_url(settings.redis_url)
    sub = r.pubsub(ignore_subscribe_messages=True)
    await sub.subscribe(CHANNEL_LIVE)

    async def pump():
        async for msg in sub.listen():
            await ws.send_text(msg["data"].decode() if isinstance(msg["data"], bytes) else msg["data"])

    async def drain():
        # read (and ignore) client frames so a closed socket is noticed
        while True:
            await ws.receive_text()

    tasks = [asyncio.create_task(pump()), asyncio.create_task(drain())]
    try:
        await ws.send_text(json.dumps({"type": "hello"}))
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        for t in tasks:
            t.cancel()
        await sub.unsubscribe(CHANNEL_LIVE)
        await sub.aclose()
        await r.aclose()


# ---- built dashboard (npm run build in web/) with single-page-app fallback ----
if WEB_DIST.exists():

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(("api/", "ws/")):
            raise HTTPException(404, "not found")
        file = (WEB_DIST / path).resolve()
        if path and file.is_file() and WEB_DIST.resolve() in file.parents:
            return FileResponse(file)
        return FileResponse(WEB_DIST / "index.html")
else:

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "message": "LMS API running. Build the dashboard with `npm run build` in web/.",
            "docs": "/docs",
        }
