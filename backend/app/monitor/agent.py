"""MonitorAgent：订阅 EventBus，每 N 秒用独立 LLM 分析全链路健康状态。"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from app.tracing.events import TraceEvent, bus
from app.tracing.store import TraceStore

log = logging.getLogger(__name__)


class MonitorAgent:
    """
    独立监控 Agent：
    - 订阅 EventBus，缓存最近 N 条 TraceEvent
    - 每 interval_sec 秒调用轻量 LLM 分析：延迟/错误/模型成本
    - 最新分析摘要缓存在内存供 API 查询
    - WebSocket 订阅者实时推送原始事件流
    """

    def __init__(
        self,
        store: TraceStore,
        base_url: str,
        api_key: str,
        model: str,
        interval_sec: int = 20,
    ) -> None:
        self._store = store
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._interval = interval_sec

        self._event_buf: list[dict] = []
        self._buf_lock = asyncio.Lock()
        self._latest_summary: dict[str, Any] = {}
        self._ws_queues: list[asyncio.Queue] = []
        self._running = False

    # ── WebSocket 订阅 ────────────────────────────────────────────────────────

    def subscribe_ws(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._ws_queues.append(q)
        return q

    def unsubscribe_ws(self, q: asyncio.Queue) -> None:
        self._ws_queues = [x for x in self._ws_queues if x is not q]

    def _broadcast(self, payload: dict) -> None:
        for q in list(self._ws_queues):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    # ── 主循环 ────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._running = True
        q = bus.subscribe()
        log.info("[Monitor] 启动，分析间隔=%ds 模型=%s", self._interval, self._model)
        asyncio.create_task(self._consume_loop(q))
        asyncio.create_task(self._analyze_loop())

    async def _consume_loop(self, q: asyncio.Queue[TraceEvent]) -> None:
        while self._running:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=1.0)
                d = ev.to_dict()
                async with self._buf_lock:
                    self._event_buf.append(d)
                    if len(self._event_buf) > 500:
                        self._event_buf = self._event_buf[-500:]
                self._broadcast({"type": "trace", "event": d})
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                log.debug("[Monitor] consume error: %s", e)

    async def _analyze_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._interval)
            try:
                await self._run_analysis()
            except Exception as e:
                log.warning("[Monitor] 分析异常: %s", e)

    async def _run_analysis(self) -> None:
        async with self._buf_lock:
            events = list(self._event_buf[-100:])

        if not events:
            return

        stats = self._compute_quick_stats(events)
        prompt = self._build_prompt(events, stats)

        t0 = time.perf_counter()
        llm_reply = await self._call_llm(prompt)
        latency_ms = (time.perf_counter() - t0) * 1000

        summary = {
            "ts": time.time(),
            "analyzed_events": len(events),
            "stats": stats,
            "llm_analysis": llm_reply,
            "monitor_latency_ms": round(latency_ms, 1),
            "model": self._model,
        }
        self._latest_summary = summary
        self._broadcast({"type": "monitor_summary", "summary": summary})
        log.info("[Monitor] 分析完成 %.0fms — %s",
                 latency_ms, llm_reply.get("health", "?"))

    def _compute_quick_stats(self, events: list[dict]) -> dict:
        from collections import defaultdict
        stage_ms: dict[str, list[float]] = defaultdict(list)
        errors = 0
        models: set[str] = set()
        total_tokens_in = total_tokens_out = 0

        for e in events:
            if e.get("duration_ms"):
                stage_ms[e["stage"]].append(e["duration_ms"])
            if e.get("status") == "error":
                errors += 1
            if e.get("model"):
                models.add(e["model"])
            total_tokens_in  += e.get("tokens_in", 0)
            total_tokens_out += e.get("tokens_out", 0)

        return {
            "stage_avg_ms": {
                k: round(sum(v)/len(v), 1) for k, v in stage_ms.items()
            },
            "error_count": errors,
            "models_used": list(models),
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
        }

    def _build_prompt(self, events: list[dict], stats: dict) -> str:
        recent_errors = [
            e for e in events if e.get("status") == "error"
        ][-5:]
        slow = sorted(
            [e for e in events if (e.get("duration_ms") or 0) > 3000],
            key=lambda x: x.get("duration_ms", 0), reverse=True,
        )[:3]

        return f"""你是一个工业AI系统的全链路监控专家。
分析以下最近 {len(events)} 条执行追踪事件，给出运行状况评估。

## 各阶段平均耗时（ms）
{json.dumps(stats['stage_avg_ms'], ensure_ascii=False, indent=2)}

## Token 消耗
输入: {stats['total_tokens_in']}  输出: {stats['total_tokens_out']}

## 使用模型
{', '.join(stats['models_used']) or '暂无'}

## 错误事件（最近5条）
{json.dumps(recent_errors, ensure_ascii=False, indent=2) if recent_errors else '无'}

## 慢速事件（>3s，最多3条）
{json.dumps(slow, ensure_ascii=False, indent=2) if slow else '无'}

请输出 JSON，字段：
- health: "healthy"/"degraded"/"critical"
- summary: 一句话总结（中文，≤50字）
- bottleneck: 最慢阶段名称（如无则 null）
- cost_estimate_usd: 估算 API 费用（按 $1/1M token 粗估，保留4位小数）
- recommendations: 建议列表（≤3条，每条≤30字）
只输出 JSON，不要围栏。"""

    async def _call_llm(self, prompt: str) -> dict:
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 400,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                json=payload, headers=headers,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"]

        # 提取 JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            import re
            m = re.search(r'\{.*\}', text, re.DOTALL)
            if m:
                return json.loads(m.group())
            return {"health": "unknown", "summary": text[:100], "error": "parse_failed"}

    @property
    def latest_summary(self) -> dict:
        return self._latest_summary

    def stop(self) -> None:
        self._running = False


# ── 全局单例 ──────────────────────────────────────────────────────────────────

_monitor: MonitorAgent | None = None


def get_monitor() -> MonitorAgent | None:
    return _monitor


def init_monitor(store: TraceStore, settings) -> MonitorAgent:
    global _monitor
    _monitor = MonitorAgent(
        store=store,
        base_url=settings.monitor_base_url,
        api_key=settings.monitor_api_key,
        model=settings.monitor_model,
        interval_sec=settings.monitor_interval_sec,
    )
    return _monitor
