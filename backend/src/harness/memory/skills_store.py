"""技能库：SQLite 持久化 + FTS5 检索，Hermes 风格的可复用审核技能。"""
from __future__ import annotations
import json
import sqlite3
import uuid
import datetime
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
    skill_id     TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    dimension    TEXT,
    pattern      TEXT,
    solution     TEXT,
    example_in   TEXT,
    example_out  TEXT,
    used_count   INTEGER DEFAULT 0,
    created_at   TEXT,
    tags         TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
    skill_id,
    name,
    dimension,
    pattern,
    solution,
    tags,
    tokenize='trigram'
);
"""

class SkillsStore:
    """技能的 CRUD 和 FTS5 检索。可接入已有 Repository 的同一 DB 或独立文件。"""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        with self._conn:
            self._conn.executescript(_SCHEMA)

    def save(
        self,
        name: str,
        dimension: str,
        pattern: str,
        solution: str,
        example_in: str = "",
        example_out: str = "",
        tags: list[str] | None = None,
    ) -> str:
        skill_id = f"{dimension}_{name}_{uuid.uuid4().hex[:6]}"
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        now = datetime.datetime.now().isoformat()
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO skills "
                "(skill_id, name, dimension, pattern, solution, example_in, example_out, created_at, tags) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (skill_id, name, dimension, pattern, solution, example_in, example_out, now, tags_json),
            )
            # 删除旧索引项（FTS5独立表：先查rowid再删）
            cur2 = self._conn.execute(
                "SELECT rowid FROM skills_fts WHERE skill_id = ?", (skill_id,)
            )
            old = cur2.fetchone()
            if old:
                self._conn.execute("DELETE FROM skills_fts WHERE rowid = ?", (old[0],))
            self._conn.execute(
                "INSERT INTO skills_fts (skill_id, name, dimension, pattern, solution, tags) "
                "VALUES (?,?,?,?,?,?)",
                (skill_id, name, dimension, pattern, solution, " ".join(tags or [])),
            )
        log.info("技能已保存: %s [%s]", name, dimension)
        return skill_id

    def search(self, query: str, dimension: str | None = None, top_k: int = 3) -> list[dict[str, Any]]:
        import jieba
        tokens = [t for t in jieba.lcut(query) if len(t.strip()) > 1]
        fts_query = " OR ".join(f'"{t}"' for t in tokens[:8]) if tokens else query
        try:
            if dimension:
                cur = self._conn.execute(
                    "SELECT s.* FROM skills_fts f JOIN skills s ON s.skill_id = f.skill_id "
                    "WHERE skills_fts MATCH ? AND s.dimension = ? LIMIT ?",
                    (fts_query, dimension, top_k),
                )
            else:
                cur = self._conn.execute(
                    "SELECT s.* FROM skills_fts f JOIN skills s ON s.skill_id = f.skill_id "
                    "WHERE skills_fts MATCH ? LIMIT ?",
                    (fts_query, top_k),
                )
            rows = [dict(r) for r in cur.fetchall()]
            if rows:
                return rows
        except sqlite3.OperationalError:
            pass
        # LIKE 兜底
        like_q = f"%{query}%"
        if dimension:
            cur = self._conn.execute(
                "SELECT * FROM skills WHERE (pattern LIKE ? OR solution LIKE ?) AND dimension = ? LIMIT ?",
                (like_q, like_q, dimension, top_k),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM skills WHERE pattern LIKE ? OR solution LIKE ? LIMIT ?",
                (like_q, like_q, top_k),
            )
        return [dict(r) for r in cur.fetchall()]

    def increment_used(self, skill_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE skills SET used_count = used_count + 1 WHERE skill_id = ?",
                (skill_id,),
            )

    def all_for_dimension(self, dimension: str) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT * FROM skills WHERE dimension = ? ORDER BY used_count DESC",
            (dimension,),
        )
        return [dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
