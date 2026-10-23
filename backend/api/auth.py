"""Single-admin login with JWT. The dashboard sends `Authorization: Bearer <token>`; the
WebSocket and the <img> video stream can't set headers, so they pass `?token=` instead."""

import hmac
import time

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from backend.config import settings

ALGO = "HS256"
TOKEN_HOURS = 12
router = APIRouter(prefix="/api/auth", tags=["auth"])


class Login(BaseModel):
    username: str
    password: str


def make_token(user: str) -> str:
    now = int(time.time())
    return jwt.encode({"sub": user, "iat": now, "exp": now + TOKEN_HOURS * 3600}, settings.jwt_secret, ALGO)


def verify(token: str) -> str:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGO])["sub"]
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token") from e


def require_user(request: Request, token: str | None = Query(None)) -> str:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:]
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login required")
    return verify(token)


@router.post("/login")
def login(body: Login) -> dict:
    if not settings.admin_password or not settings.jwt_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "API_ADMIN_PASSWORD / API_JWT_SECRET not set")
    ok_user = hmac.compare_digest(body.username, settings.admin_user)
    ok_pass = hmac.compare_digest(body.password, settings.admin_password)
    if not (ok_user and ok_pass):
        time.sleep(0.5)  # slow down guessing
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong username or password")
    return {"token": make_token(body.username), "expires_in": TOKEN_HOURS * 3600}


@router.get("/me")
def me(user: str = Depends(require_user)) -> dict:
    return {"user": user}
