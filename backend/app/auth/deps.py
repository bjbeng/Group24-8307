from __future__ import annotations
from fastapi import Cookie, Depends, HTTPException, Header, Request, status
from app.auth.core import decode_token


def current_user(
    access_token: str | None = Cookie(default=None),
) -> str:
    """所有需要鉴权的路由都必须通过这个依赖。"""
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    user_id = decode_token(access_token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token 无效或已过期")
    return user_id


def get_csrf_token(request: Request) -> str:
    token = request.cookies.get("csrf_token", "")
    return token


def verify_csrf(
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    csrf_token: str = Depends(get_csrf_token),
) -> None:
    """POST/DELETE 接口用此依赖校验 CSRF token。"""
    if not csrf_token or not x_csrf_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token 缺失")
    if x_csrf_token != csrf_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token 不匹配")
