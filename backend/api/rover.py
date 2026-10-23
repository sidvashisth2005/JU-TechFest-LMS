"""Proxy to the rover server on the Pi, so the dashboard only ever talks to this API
(one origin, one login) and the Pi is never exposed to the internet directly."""

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.api.auth import require_user
from backend.config import settings

router = APIRouter(prefix="/api/rover", tags=["rover"], dependencies=[Depends(require_user)])
TIMEOUT = httpx.Timeout(3.0, read=5.0)


def _url(path: str) -> str:
    if not settings.rover_url:
        raise HTTPException(503, "ROVER_URL not configured")
    return settings.rover_url.rstrip("/") + path


async def _forward(method: str, path: str, json=None):
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.request(method, _url(path), json=json)
    except httpx.HTTPError as e:
        raise HTTPException(503, f"rover unreachable: {type(e).__name__}") from e
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text[:300])
    return r.json()


@router.get("/status")
async def status():
    return await _forward("GET", "/status")


@router.post("/control")
async def control(request: Request):
    return await _forward("POST", "/control", await request.json())


@router.post("/mode")
async def mode(request: Request):
    return await _forward("POST", "/mode", await request.json())


@router.get("/stream.mjpg")
async def stream():
    client = httpx.AsyncClient(timeout=httpx.Timeout(3.0, read=None))
    try:
        req = client.build_request("GET", _url("/stream.mjpg"))
        resp = await client.send(req, stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        raise HTTPException(503, f"rover unreachable: {type(e).__name__}") from e

    async def body():
        try:
            async for chunk in resp.aiter_raw():
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(body(), media_type=resp.headers.get("content-type", "multipart/x-mixed-replace"))
