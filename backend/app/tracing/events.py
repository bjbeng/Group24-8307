"""全链路埋点事件定义 + 全局异步事件总线。"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Literal


Stage = Literal[
    "ingest", "chunk", "assign_dims",
    "explorer_a_start", "explorer_a_done",
    "explorer_b_start", "explorer_b_done",
    "sub_agent_start", "sub_agent_done",
    "critic_start", "critic_done",
    "persist", "pipeline_done", "pipeline_error",
]

Status = Literal["start", "done", "error"]


@dataclass
class TraceEvent:
    task_id: str
    stage: Stage
    status: Status
    ts: float = field(default_factory=time.time)
    doc_id: str = ""
    dimension: str = ""
    model: str = ""
    duration_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    error: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "stage": self.stage,
            "status": self.status,
            "ts": self.ts,
            "doc_id": self.doc_id,
            "dimension": self.dimension,
            "model": self.model,
            "duration_ms": self.duration_ms,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "error": self.error,
            "extra": self.extra,
        }


class EventBus:
    """广播给所有订阅者（WebSocket 连接 + MonitorAgent）。"""

    def __init__(self) -> None:
        self._queues: list[asyncio.Queue[TraceEvent]] = []

    def subscribe(self) -> asyncio.Queue[TraceEvent]:
        q: asyncio.Queue[TraceEvent] = asyncio.Queue(maxsize=500)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[TraceEvent]) -> None:
        self._queues = [x for x in self._queues if x is not q]

    def emit(self, event: TraceEvent) -> None:
        """同步发射（可从线程池调用）。"""
        for q in list(self._queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    async def aemit(self, event: TraceEvent) -> None:
        self.emit(event)


# 全局单例
bus = EventBus()
