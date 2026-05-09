"""把埋点挂进引擎的 hooks registry（pre/post agent run）。"""
from __future__ import annotations

import time
from typing import Any

from .events import TraceEvent, bus
from .store import TraceStore

_store: TraceStore | None = None


def init_trace_store(db_path: str) -> TraceStore:
    global _store
    _store = TraceStore(db_path)
    return _store


def get_store() -> TraceStore | None:
    return _store


def _emit(ev: TraceEvent) -> None:
    bus.emit(ev)
    if _store:
        try:
            _store.write(ev)
        except Exception:
            pass


# ── 引擎 hook 回调 ────────────────────────────────────────────────────────────
# 在 label_pipeline / audit_pipeline 里调用

def on_pipeline_start(task_id: str, doc_id: str, scenario: str) -> None:
    _emit(TraceEvent(
        task_id=task_id, stage="ingest", status="start",
        doc_id=doc_id, extra={"scenario": scenario},
    ))


def on_ingest_done(task_id: str, doc_id: str, n_chunks: int, elapsed_ms: float) -> None:
    _emit(TraceEvent(
        task_id=task_id, stage="ingest", status="done",
        doc_id=doc_id, duration_ms=elapsed_ms,
        extra={"n_chunks": n_chunks},
    ))


def on_explorer_start(task_id: str, doc_id: str, role: str, model: str) -> None:
    stage = "explorer_a_start" if role == "a" else "explorer_b_start"
    _emit(TraceEvent(
        task_id=task_id, stage=stage, status="start",
        doc_id=doc_id, model=model,
    ))


def on_explorer_done(task_id: str, doc_id: str, role: str, model: str,
                     elapsed_ms: float, n_dims: int) -> None:
    stage = "explorer_a_done" if role == "a" else "explorer_b_done"
    _emit(TraceEvent(
        task_id=task_id, stage=stage, status="done",
        doc_id=doc_id, model=model, duration_ms=elapsed_ms,
        extra={"n_dims": n_dims},
    ))


def on_sub_agent_start(task_id: str, doc_id: str, dimension: str, model: str) -> None:
    _emit(TraceEvent(
        task_id=task_id, stage="sub_agent_start", status="start",
        doc_id=doc_id, dimension=dimension, model=model,
    ))


def on_sub_agent_done(task_id: str, doc_id: str, dimension: str, model: str,
                      verdict: str, elapsed_ms: float,
                      tokens_in: int = 0, tokens_out: int = 0) -> None:
    _emit(TraceEvent(
        task_id=task_id, stage="sub_agent_done", status="done",
        doc_id=doc_id, dimension=dimension, model=model,
        duration_ms=elapsed_ms, tokens_in=tokens_in, tokens_out=tokens_out,
        extra={"verdict": verdict},
    ))


def on_sub_agent_error(task_id: str, doc_id: str, dimension: str, error: str) -> None:
    _emit(TraceEvent(
        task_id=task_id, stage="sub_agent_done", status="error",
        doc_id=doc_id, dimension=dimension, error=error,
    ))


def on_critic_start(task_id: str, doc_id: str, model: str, n_divergent: int) -> None:
    _emit(TraceEvent(
        task_id=task_id, stage="critic_start", status="start",
        doc_id=doc_id, model=model, extra={"n_divergent": n_divergent},
    ))


def on_critic_done(task_id: str, doc_id: str, model: str,
                   elapsed_ms: float, tokens_in: int = 0, tokens_out: int = 0) -> None:
    _emit(TraceEvent(
        task_id=task_id, stage="critic_done", status="done",
        doc_id=doc_id, model=model, duration_ms=elapsed_ms,
        tokens_in=tokens_in, tokens_out=tokens_out,
    ))


def on_pipeline_done(task_id: str, doc_id: str, total_ms: float, n_dims: int) -> None:
    _emit(TraceEvent(
        task_id=task_id, stage="pipeline_done", status="done",
        doc_id=doc_id, duration_ms=total_ms, extra={"n_dims": n_dims},
    ))


def on_pipeline_error(task_id: str, doc_id: str, error: str) -> None:
    _emit(TraceEvent(
        task_id=task_id, stage="pipeline_error", status="error",
        doc_id=doc_id, error=error,
    ))
