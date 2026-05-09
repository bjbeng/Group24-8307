"""单文档会话：状态跟踪与断点续传。"""
from __future__ import annotations
import datetime
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger(__name__)

_SESSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS doc_sessions (
    session_id     TEXT PRIMARY KEY,
    doc_id         TEXT NOT NULL,
    doc_path       TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',
    completed_dims TEXT DEFAULT '[]',
    failed_dims    TEXT DEFAULT '[]',
    started_at     TEXT,
    checkpoint_at  TEXT,
    finished_at    TEXT,
    error_msg      TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_doc ON doc_sessions(doc_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON doc_sessions(status);
"""

@dataclass
class DocSessionState:
    session_id: str
    doc_id: str
    doc_path: str
    status: Literal["pending", "ingesting", "auditing", "aggregating", "done", "failed"] = "pending"
    completed_dims: list[str] = field(default_factory=list)
    failed_dims: list[str] = field(default_factory=list)
    started_at: str = ""
    checkpoint_at: str = ""
    finished_at: str = ""
    error_msg: str = ""

    def remaining_dims(self, all_dims: list[str]) -> list[str]:
        done = set(self.completed_dims)
        return [d for d in all_dims if d not in done]

class DocSession:
    """DocSessionState 的持久化管理器。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(_SESSION_SCHEMA)

    def create(self, doc_id: str, doc_path: str) -> DocSessionState:
        import uuid
        session_id = f"sess_{doc_id}_{uuid.uuid4().hex[:8]}"
        now = datetime.datetime.now().isoformat()
        state = DocSessionState(
            session_id=session_id, doc_id=doc_id, doc_path=doc_path,
            status="pending", started_at=now,
        )
        self._upsert(state)
        return state

    def get(self, session_id: str) -> DocSessionState | None:
        cur = self._conn.execute(
            "SELECT * FROM doc_sessions WHERE session_id = ?", (session_id,)
        )
        row = cur.fetchone()
        return self._from_row(row) if row else None

    def get_by_doc(self, doc_id: str) -> list[DocSessionState]:
        cur = self._conn.execute(
            "SELECT * FROM doc_sessions WHERE doc_id = ? ORDER BY started_at DESC",
            (doc_id,),
        )
        return [self._from_row(r) for r in cur.fetchall() if r]

    def update_status(self, session_id: str, status: str) -> None:
        now = datetime.datetime.now().isoformat()
        with self._conn:
            self._conn.execute(
                "UPDATE doc_sessions SET status=?, checkpoint_at=? WHERE session_id=?",
                (status, now, session_id),
            )

    def mark_dim_done(self, session_id: str, dimension: str) -> None:
        state = self.get(session_id)
        if not state:
            return
        if dimension not in state.completed_dims:
            state.completed_dims.append(dimension)
        state.checkpoint_at = datetime.datetime.now().isoformat()
        self._upsert(state)

    def mark_dim_failed(self, session_id: str, dimension: str) -> None:
        state = self.get(session_id)
        if not state:
            return
        if dimension not in state.failed_dims:
            state.failed_dims.append(dimension)
        self._upsert(state)

    def finish(self, session_id: str, error: str = "") -> None:
        now = datetime.datetime.now().isoformat()
        status = "failed" if error else "done"
        with self._conn:
            self._conn.execute(
                "UPDATE doc_sessions SET status=?, finished_at=?, error_msg=? WHERE session_id=?",
                (status, now, error, session_id),
            )

    def _upsert(self, state: DocSessionState) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO doc_sessions
                (session_id, doc_id, doc_path, status, completed_dims, failed_dims,
                 started_at, checkpoint_at, finished_at, error_msg)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    state.session_id, state.doc_id, state.doc_path, state.status,
                    json.dumps(state.completed_dims, ensure_ascii=False),
                    json.dumps(state.failed_dims, ensure_ascii=False),
                    state.started_at, state.checkpoint_at, state.finished_at, state.error_msg,
                ),
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> DocSessionState:
        d = dict(row)
        def _j(v: Any) -> list:
            if isinstance(v, str) and v:
                try:
                    return json.loads(v)
                except Exception:
                    pass
            return []
        return DocSessionState(
            session_id=d["session_id"], doc_id=d["doc_id"], doc_path=d["doc_path"],
            status=d.get("status", "pending"),
            completed_dims=_j(d.get("completed_dims")),
            failed_dims=_j(d.get("failed_dims")),
            started_at=d.get("started_at", ""),
            checkpoint_at=d.get("checkpoint_at", ""),
            finished_at=d.get("finished_at", ""),
            error_msg=d.get("error_msg", ""),
        )

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
