from __future__ import annotations
import secrets
import sqlite3
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from app.auth.core import hash_password, verify_password, create_access_token, make_csrf_token
from app.auth.deps import current_user, verify_csrf
from app.config import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _get_db() -> sqlite3.Connection:
    s = get_settings()
    Path(s.engine_db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(s.engine_db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            nickname TEXT NOT NULL DEFAULT '',
            avatar TEXT NOT NULL DEFAULT '',
            hashed_password TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn


class AuthBody(BaseModel):
    username: str
    password: str


@router.post("/register")
async def register(body: AuthBody, response: Response) -> dict:
    if len(body.username) < 2 or len(body.username) > 50:
        raise HTTPException(400, "用户名长度 2-50 字符")
    if len(body.password) < 8:
        raise HTTPException(400, "密码至少 8 字符")
    import uuid
    user_id = uuid.uuid4().hex
    hashed = hash_password(body.password)
    db = _get_db()
    try:
        db.execute("INSERT INTO users (user_id, username, hashed_password) VALUES (?,?,?)",
                   (user_id, body.username, hashed))
        db.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(409, "用户名已存在")
    finally:
        db.close()
    s = get_settings()
    token = create_access_token(user_id)
    csrf = make_csrf_token()
    response.set_cookie("access_token", token, httponly=s.cookie_httponly,
                        secure=s.cookie_secure, samesite=s.cookie_samesite, max_age=86400, path="/")
    response.set_cookie("csrf_token", csrf, httponly=False,
                        secure=s.cookie_secure, samesite=s.cookie_samesite, max_age=86400, path="/")
    return {"user_id": user_id, "username": body.username, "nickname": body.username, "avatar": ""}


@router.post("/login")
async def login(body: AuthBody, response: Response) -> dict:
    db = _get_db()
    try:
        row = db.execute("SELECT user_id, username, nickname, avatar, hashed_password FROM users WHERE username=?",
                         (body.username,)).fetchone()
    finally:
        db.close()
    if not row or not verify_password(body.password, row[4]):
        raise HTTPException(401, "用户名或密码错误")
    s = get_settings()
    token = create_access_token(row[0])
    csrf = make_csrf_token()
    response.set_cookie("access_token", token, httponly=s.cookie_httponly,
                        secure=s.cookie_secure, samesite=s.cookie_samesite, max_age=86400, path="/")
    response.set_cookie("csrf_token", csrf, httponly=False,
                        secure=s.cookie_secure, samesite=s.cookie_samesite, max_age=86400, path="/")
    return {"user_id": row[0], "username": row[1], "nickname": row[2] or row[1], "avatar": row[3] or ""}


@router.post("/logout", dependencies=[Depends(verify_csrf)])
async def logout(response: Response, user_id: str = Depends(current_user)) -> dict:
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("csrf_token", path="/")
    return {"ok": True}


@router.get("/me")
async def me(user_id: str = Depends(current_user)) -> dict:
    db = _get_db()
    try:
        row = db.execute("SELECT user_id, username, nickname, avatar FROM users WHERE user_id=?",
                         (user_id,)).fetchone()
    finally:
        db.close()
    if not row:
        return {"user_id": user_id, "username": "", "nickname": "", "avatar": ""}
    return {"user_id": row[0], "username": row[1], "nickname": row[2] or row[1], "avatar": row[3] or ""}
