"""把 TraceEvent 持久化到 SQLite trace_events 表。"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from .events import TraceEvent

_DDL = """
CREATE TABLE IF NOT EXISTS trace_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT    NOT NULL,
    stage       TEXT    NOT NULL,
    status      TEXT    NOT NULL,
    ts          REAL    NOT NULL,
    doc_id      TEXT    DEFAULT '',
    dimension   TEXT    DEFAULT '',
    model       TEXT    DEFAULT '',
    duration_ms REAL    DEFAULT 0,
    tokens_in   INTEGER DEFAULT 0,
    tokens_out  INTEGER DEFAULT 0,
    error       TEXT    DEFAULT '',
    extra       TEXT    DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_trace_task ON trace_events(task_id);
CREATE INDEX IF NOT EXISTS ix_trace_ts   ON trace_events(ts);
"""

_INSERT = """
INSERT INTO trace_events
  (task_id, stage, status, ts, doc_id, dimension, model,
   duration_ms, tokens_in, tokens_out, error, extra)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
"""


class TraceStore:
    def __init__(self, db_path: str) -> None:
        self._path = db_path
        self._lock = threading.Lock()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, check_same_thread=False)

    def _init_db(self) -> None:
        with self._lock, self._conn() as conn:
            conn.executescript(_DDL)

    def write(self, ev: TraceEvent) -> None:
        import json
        with self._lock, self._conn() as conn:
            conn.execute(_INSERT, (
                ev.task_id, ev.stage, ev.status, ev.ts,
                ev.doc_id, ev.dimension, ev.model,
                ev.duration_ms, ev.tokens_in, ev.tokens_out,
                ev.error, json.dumps(ev.extra, ensure_ascii=False),
            ))

    def recent(self, limit: int = 200, task_id: str = "") -> list[dict]:
        import json
        with self._lock, self._conn() as conn:
            if task_id:
                rows = conn.execute(
                    "SELECT * FROM trace_events WHERE task_id=? ORDER BY ts DESC LIMIT ?",
                    (task_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM trace_events ORDER BY ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        cols = ["id","task_id","stage","status","ts","doc_id","dimension",
                "model","duration_ms","tokens_in","tokens_out","error","extra"]
        result = []
        for row in rows:
            d = dict(zip(cols, row))
            try:
                d["extra"] = json.loads(d["extra"])
            except Exception:
                pass
            result.append(d)
        return result

    def stats(self, task_id: str = "") -> dict:
        """返回汇总统计：各 stage 平均耗时、总 token 数、error 数。"""
        with self._lock, self._conn() as conn:
            if task_id:
                where = "WHERE task_id=?"
                params: tuple = (task_id,)
            else:
                where, params = "", ()
            rows = conn.execute(
                f"""SELECT stage, AVG(duration_ms), SUM(tokens_in),
                           SUM(tokens_out), SUM(CASE WHEN status='error' THEN 1 ELSE 0 END)
                    FROM trace_events {where}
                    GROUP BY stage""",
                params,
            ).fetchall()
        return {
            r[0]: {
                "avg_ms": round(r[1] or 0, 1),
                "tokens_in": r[2] or 0,
                "tokens_out": r[3] or 0,
                "errors": r[4] or 0,
            }
            for r in rows
        }
