from __future__ import annotations
import asyncio
import datetime
import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Awaitable

from app.config import get_settings


log = logging.getLogger(__name__)

# ── SQLite 持久化 ─────────────────────────────────────────────────────────────

def _default_total(scenario: str, mode: str) -> int:
    if scenario == "s2":
        return 19
    if mode == "label":
        return 8
    return 11


def _db_path() -> str:
    return get_settings().engine_db_path


_db_lock = threading.Lock()

_DDL = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id     TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL DEFAULT '',
    file_name   TEXT NOT NULL DEFAULT '',
    scenario    TEXT NOT NULL DEFAULT 's1',
    mode        TEXT NOT NULL DEFAULT 'audit',
    status      TEXT NOT NULL DEFAULT 'pending',
    progress    INTEGER NOT NULL DEFAULT 0,
    total       INTEGER NOT NULL DEFAULT 11,
    result      TEXT,
    error       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_tasks_user ON tasks(user_id);
CREATE INDEX IF NOT EXISTS ix_tasks_created ON tasks(created_at DESC);
"""


def _conn() -> sqlite3.Connection:
    db_path = _db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db_path, check_same_thread=False)


def _ensure_table() -> None:
    with _db_lock, _conn() as c:
        c.executescript(_DDL)


def _insert_task(t: "TaskStatus") -> None:
    with _db_lock, _conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO tasks
               (task_id, user_id, file_name, scenario, mode,
                status, progress, total, result, error, created_at, finished_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (t.task_id, t.user_id, t.file_name, t.scenario, t.mode,
             t.status, t.progress, t.total,
             json.dumps(t.result, ensure_ascii=False) if t.result else None,
             t.error, t.created_at, t.finished_at),
        )


def _update_task(t: "TaskStatus") -> None:
    with _db_lock, _conn() as c:
        c.execute(
            """UPDATE tasks SET status=?, progress=?, total=?, result=?,
               error=?, finished_at=? WHERE task_id=?""",
            (t.status, t.progress, t.total,
             json.dumps(t.result, ensure_ascii=False) if t.result else None,
             t.error, t.finished_at, t.task_id),
        )


def _row_to_status(row: tuple) -> "TaskStatus":
    cols = ["task_id", "user_id", "file_name", "scenario", "mode",
            "status", "progress", "total", "result", "error",
            "created_at", "finished_at"]
    d = dict(zip(cols, row))
    result = None
    if d["result"]:
        try:
            result = json.loads(d["result"])
        except Exception:
            pass
    return TaskStatus(
        task_id=d["task_id"], user_id=d["user_id"],
        file_name=d["file_name"], scenario=d["scenario"], mode=d["mode"],
        status=d["status"], progress=d["progress"], total=d["total"],
        result=result, summary=_build_summary(result), error=d["error"] or "",
        created_at=d["created_at"], finished_at=d["finished_at"] or "",
    )


def _build_summary(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not result:
        return None

    dimensions = result.get("dimensions") or {}
    dimension_summaries = [
        {
            "dimension": dim_key,
            "verdict": dim_value.get("verdict"),
            "findings_count": len(dim_value.get("findings") or []),
            "score": dim_value.get("score"),
            "confidence": dim_value.get("confidence"),
        }
        for dim_key, dim_value in dimensions.items()
    ]

    return {
        "doc_id": result.get("doc_id"),
        "doc_name": result.get("doc_name"),
        "overall_verdict": result.get("overall_verdict"),
        "overall_score": result.get("overall_score"),
        "need_human_review": result.get("need_human_review"),
        "elapsed_seconds": result.get("elapsed_seconds"),
        "dimensions_completed": len(dimension_summaries),
        "dimension_summaries": dimension_summaries,
    }


# ── 数据模型 ──────────────────────────────────────────────────────────────────

@dataclass
class TaskStatus:
    task_id: str
    user_id: str = ""
    file_name: str = ""
    scenario: str = "s1"
    mode: str = "audit"
    status: str = "pending"
    progress: int = 0
    total: int = 11
    result: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    error: str = ""
    created_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    finished_at: str = ""


# 内存缓存（减少 DB 查询）
_tasks: dict[str, TaskStatus] = {}
_progress_callbacks: dict[str, list[Callable]] = {}

_ensure_table()


# ── 公共 API ──────────────────────────────────────────────────────────────────

async def submit_task(
    audit_fn: Callable[..., Awaitable[dict[str, Any]]],
    doc_path: str,
    config_override: dict | None = None,
    user_id: str = "",
    file_name: str = "",
) -> str:
    task_id = uuid.uuid4().hex
    scenario = (config_override or {}).get("scenario", "s1")
    mode = (config_override or {}).get("mode", "audit")
    t = TaskStatus(
        task_id=task_id, user_id=user_id,
        file_name=file_name, scenario=scenario, mode=mode,
        total=_default_total(scenario, mode),
    )
    _tasks[task_id] = t
    _insert_task(t)

    # 把 task_id 注入 config，供 audit route 里埋点用
    if config_override is None:
        config_override = {}
    config_override["_task_id"] = task_id

    asyncio.create_task(_run_task(task_id, audit_fn, doc_path, config_override))
    return task_id


async def _run_task(task_id: str, fn, doc_path, config_override):
    t = _tasks[task_id]
    t.status = "running"
    _update_task(t)
    try:
        result = await fn(
            doc_path,
            config_override=config_override,
            progress_cb=lambda dim, verdict: _on_progress(task_id, dim, verdict),
        )
        t.result = result
        t.summary = _build_summary(result)
        t.total = max(t.total, len((result or {}).get("dimensions") or {}))
        t.progress = t.total
        t.status = "done"
        log.info(
            "task DONE task=%s scenario=%s mode=%s stored_result=%s dimensions=%d",
            task_id[:8],
            t.scenario,
            t.mode,
            bool(result),
            len((result or {}).get("dimensions") or {}),
        )
    except Exception as e:
        t.error = str(e)
        t.status = "failed"
    finally:
        t.finished_at = datetime.datetime.now().isoformat()
        _update_task(t)


def _on_progress(task_id: str, dimension: str, verdict: str) -> None:
    t = _tasks.get(task_id)
    if t:
        t.progress += 1
        _update_task(t)
    for cb in _progress_callbacks.get(task_id, []):
        try:
            cb(task_id, dimension, verdict)
        except Exception:
            pass


def get_task(task_id: str) -> TaskStatus | None:
    if task_id in _tasks:
        return _tasks[task_id]
    # 内存缓存未命中，从 DB 加载（服务重启后的历史任务）
    with _db_lock, _conn() as c:
        row = c.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    if row:
        t = _row_to_status(row)
        _tasks[task_id] = t
        return t
    return None


def list_tasks(user_id: str, limit: int = 50) -> list[TaskStatus]:
    """列出用户的历史任务（最新在前）。"""
    with _db_lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM tasks WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [_row_to_status(r) for r in rows]


def delete_task(task_id: str, user_id: str) -> bool:
    """删除任务记录，返回是否实际删除了行。"""
    with _db_lock, _conn() as c:
        cur = c.execute(
            "DELETE FROM tasks WHERE task_id=? AND user_id=?",
            (task_id, user_id),
        )
        deleted = cur.rowcount > 0
    _tasks.pop(task_id, None)
    return deleted


def register_progress_callback(task_id: str, cb: Callable) -> None:
    _progress_callbacks.setdefault(task_id, []).append(cb)


def unregister_callbacks(task_id: str) -> None:
    _progress_callbacks.pop(task_id, None)


task_queue = _tasks
