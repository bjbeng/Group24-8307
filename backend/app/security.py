from __future__ import annotations
import re
import time
from collections import defaultdict, deque
from pathlib import Path
from fastapi import HTTPException, Request


def safe_upload_path(upload_dir: Path, user_id: str, filename: str) -> Path:
    """
    防路径穿越：文件只能存入 upload_dir/<user_id>/。
    拒绝任何能逃出该目录的路径。
    """
    # 只取文件名，剥离所有目录部分
    safe_name = Path(filename).name
    if not safe_name or safe_name.startswith("."):
        raise HTTPException(400, "非法文件名")
    # 额外过滤危险字符
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', safe_name):
        raise HTTPException(400, "文件名包含非法字符")
    base = (upload_dir / user_id).resolve()
    base.mkdir(parents=True, exist_ok=True)
    dest = (base / safe_name).resolve()
    # 关键断言：dest 必须在 base 内（Path.relative_to 跨平台安全）
    try:
        dest.relative_to(base)
    except ValueError:
        raise HTTPException(400, "路径穿越攻击被拦截")
    return dest


# ── 速率限制（sliding window，内存实现，适合单进程） ──────────────────────

_WINDOWS: dict[str, deque] = defaultdict(deque)


def check_rate_limit(key: str, max_calls: int = 30, window_seconds: float = 60.0) -> None:
    now = time.monotonic()
    dq = _WINDOWS[key]
    while dq and now - dq[0] > window_seconds:
        dq.popleft()
    if len(dq) >= max_calls:
        raise HTTPException(429, f"请求过于频繁，请 {int(window_seconds)}s 后重试")
    dq.append(now)
