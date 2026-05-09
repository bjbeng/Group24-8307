from __future__ import annotations
import secrets
import bcrypt as _bcrypt_lib
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from app.config import get_settings


def hash_password(plain: str) -> str:
    # bcrypt 最大 72 字节，超出部分截断（与 passlib 行为一致）
    encoded = plain.encode("utf-8")[:72]
    return _bcrypt_lib.hashpw(encoded, _bcrypt_lib.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    encoded = plain.encode("utf-8")[:72]
    return _bcrypt_lib.checkpw(encoded, hashed.encode("utf-8"))


def create_access_token(subject: str, expires_minutes: int = 60 * 24) -> str:
    s = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    return jwt.encode({"sub": subject, "exp": expire}, s.secret_key, algorithm="HS256")


def decode_token(token: str) -> str | None:
    s = get_settings()
    try:
        payload = jwt.decode(token, s.secret_key, algorithms=["HS256"])
        return payload.get("sub")
    except JWTError:
        return None


def make_csrf_token() -> str:
    return secrets.token_urlsafe(32)


# Alias for compatibility with __init__.py import
def verify_token(token: str) -> str | None:
    return decode_token(token)
