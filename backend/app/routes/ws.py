from __future__ import annotations
import asyncio
import re
import time
from collections import defaultdict, deque
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.tasks.queue import get_task, register_progress_callback, unregister_callbacks

router = APIRouter(tags=["ws"])

_connections: dict[str, list[WebSocket]] = defaultdict(list)
_ws_rate: dict[str, deque] = defaultdict(deque)
_MAX_MSG_BYTES = 4096
_RATE_MAX = 30
_RATE_WINDOW = 60.0


def _check_ws_rate(client_id: str) -> bool:
    now = time.monotonic()
    dq = _ws_rate[client_id]
    while dq and now - dq[0] > _RATE_WINDOW:
        dq.popleft()
    if len(dq) >= _RATE_MAX:
        return False
    dq.append(now)
    return True


def _validate_nickname(nick: str) -> bool:
    if not nick or len(nick) > 32:
        return False
    if re.search(r'[\x00-\x1f\x7f]', nick):  # 控制字符
        return False
    return True


@router.websocket("/ws/audit/{task_id}")
async def ws_audit_progress(websocket: WebSocket, task_id: str) -> None:
    await websocket.accept()
    client_id = f"{task_id}_{id(websocket)}"
    _connections[task_id].append(websocket)

    # 注册进度回调
    def on_progress(tid: str, dimension: str, verdict: str) -> None:
        asyncio.create_task(_broadcast(task_id, {
            "type": "progress", "dimension": dimension, "verdict": verdict,
        }))

    register_progress_callback(task_id, on_progress)

    try:
        # 立即发送当前状态
        t = get_task(task_id)
        if t:
            await websocket.send_json({
                "type": "status", "status": t.status,
                "progress": t.progress, "total": t.total,
                "error": t.error,
            })
            # 任务已结束则直接关闭
            if t.status in ("done", "failed"):
                return

        # 轮询任务状态，主动推送完成/失败
        async def _watch_done() -> None:
            while True:
                await asyncio.sleep(2)
                t = get_task(task_id)
                if t and t.status in ("done", "failed"):
                    await _broadcast(task_id, {
                        "type": "status", "status": t.status,
                        "progress": t.progress, "total": t.total,
                        "error": t.error,
                    })
                    return

        asyncio.create_task(_watch_done())

        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_bytes(), timeout=30.0)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
                continue

            if len(raw) > _MAX_MSG_BYTES:
                await websocket.send_json({"type": "error", "message": "消息过大"})
                continue

            if not _check_ws_rate(client_id):
                await websocket.send_json({"type": "error", "message": "请求过于频繁"})
                continue

    except WebSocketDisconnect:
        pass
    finally:
        _connections[task_id] = [w for w in _connections[task_id] if w is not websocket]
        if not _connections[task_id]:
            unregister_callbacks(task_id)
        _ws_rate.pop(client_id, None)


async def _broadcast(task_id: str, msg: dict) -> None:
    dead = []
    for ws in _connections.get(task_id, []):
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    _connections[task_id] = [w for w in _connections[task_id] if w not in dead]
