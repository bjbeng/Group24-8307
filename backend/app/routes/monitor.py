"""Monitor API：全链路追踪查询 + 实时 WebSocket 推送。"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from app.auth.deps import current_user
from app.monitor.agent import get_monitor
from app.tracing.hooks import get_store

router = APIRouter(prefix="/api/monitor", tags=["monitor"])


@router.get("/summary")
async def get_summary(user_id: str = Depends(current_user)) -> JSONResponse:
    """最新 MonitorAgent LLM 分析摘要。"""
    m = get_monitor()
    return JSONResponse(m.latest_summary if m else {"status": "monitor_not_ready"})


@router.get("/traces")
async def get_traces(
    task_id: str = "",
    limit: int = 100,
    user_id: str = Depends(current_user),
) -> JSONResponse:
    """查询历史 trace 事件（SQLite）。"""
    store = get_store()
    if not store:
        return JSONResponse({"events": [], "error": "store_not_ready"})
    events = store.recent(limit=limit, task_id=task_id)
    return JSONResponse({"events": events, "total": len(events)})


@router.get("/stats")
async def get_stats(
    task_id: str = "",
    user_id: str = Depends(current_user),
) -> JSONResponse:
    """各阶段统计（平均耗时、token 数、错误数）。"""
    store = get_store()
    if not store:
        return JSONResponse({"error": "store_not_ready"})
    return JSONResponse(store.stats(task_id=task_id))


@router.websocket("/ws")
async def monitor_ws(websocket: WebSocket) -> None:
    """
    实时推送 TraceEvent + MonitorAgent 分析摘要。
    客户端收到两种消息：
      {"type": "trace",          "event": {...}}
      {"type": "monitor_summary","summary": {...}}
    """
    await websocket.accept()
    m = get_monitor()
    if not m:
        await websocket.send_text(json.dumps({"error": "monitor_not_ready"}))
        await websocket.close()
        return

    q = m.subscribe_ws()
    try:
        # 先发最新摘要
        if m.latest_summary:
            await websocket.send_text(json.dumps(
                {"type": "monitor_summary", "summary": m.latest_summary}
            ))

        while True:
            try:
                payload = await asyncio.wait_for(q.get(), timeout=30.0)
                await websocket.send_text(json.dumps(payload, ensure_ascii=False))
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        pass
    finally:
        m.unsubscribe_ws(q)
