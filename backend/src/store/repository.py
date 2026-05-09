"""SQLite Repository：所有 CRUD 集中在此，业务代码不直接写 SQL。"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from src.chunk.models import Chunk


_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_schema_sql() -> str:
    return _SCHEMA_PATH.read_text(encoding="utf-8")


class Repository:
    """SQLite 数据访问。

    线程安全策略：每个连接绑到调用线程，长任务自行 `with repo.connect()`。
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(get_schema_sql())
        self._migrate()

    def _migrate(self) -> None:
        """前向迁移：给已有表补充新列（幂等）。"""
        migrations = [
            "ALTER TABLE standard_versions ADD COLUMN search_snippets TEXT",
            "ALTER TABLE standard_versions ADD COLUMN fetched_at TEXT",
            "ALTER TABLE document_cache ADD COLUMN converted_docx_path TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE document_cache ADD COLUMN cache_status TEXT NOT NULL DEFAULT 'ready'",
            "ALTER TABLE document_cache ADD COLUMN updated_at TEXT",
        ]
        for sql in migrations:
            try:
                self._conn.execute(sql)
                self._conn.commit()
            except sqlite3.OperationalError:
                pass
            # 迁移：为已存在的旧库补加 bbox 列（新建库已含此列，忽略重复）
            try:
                self._conn.execute("ALTER TABLE chunks ADD COLUMN bbox TEXT")
            except Exception:
                pass

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ---------- chunks ----------

    def upsert_chunks(self, chunks: Iterable[Chunk]) -> int:
        rows = [c.to_row() for c in chunks]
        if not rows:
            return 0
        cols = list(rows[0].keys())
        placeholders = ", ".join([f":{c}" for c in cols])
        sql = (
            f"INSERT OR REPLACE INTO chunks ({', '.join(cols)}) VALUES ({placeholders})"
        )
        fts_sql = (
            "INSERT INTO chunks_fts (chunk_id, doc_id, content, title) "
            "VALUES (:chunk_id, :doc_id, :content, :title)"
        )
        with self.connect() as conn:
            conn.executemany(sql, rows)
            # FTS：先删再插（INSERT OR REPLACE 不触发 FTS 删除）
            for r in rows:
                conn.execute(
                    "DELETE FROM chunks_fts WHERE chunk_id = ?", (r["chunk_id"],)
                )
            conn.executemany(fts_sql, rows)
        return len(rows)

    def get_chunk(self, chunk_id: str) -> dict | None:
        cur = self._conn.execute(
            "SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)
        )
        row = cur.fetchone()
        return _row_to_dict(row) if row else None

    def get_chunks_by_doc(self, doc_id: str) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM chunks WHERE doc_id = ? ORDER BY paragraph_index",
            (doc_id,),
        )
        return [_row_to_dict(r) for r in cur.fetchall()]

    def get_chunks_by_dimension(self, doc_id: str, dimension: str) -> list[dict]:
        """按维度过滤；dimensions 字段是 JSON array，用 LIKE 模糊匹配。"""
        pattern = f'%"{dimension}"%'
        cur = self._conn.execute(
            "SELECT * FROM chunks WHERE doc_id = ? AND dimensions LIKE ? "
            "ORDER BY paragraph_index",
            (doc_id, pattern),
        )
        return [_row_to_dict(r) for r in cur.fetchall()]

    def search_chunks(
        self,
        query: str,
        doc_id: str | None = None,
        top_k: int = 10,
    ) -> list[dict]:
        """检索 chunks：trigram FTS5 优先，LIKE 兜底短查询。"""

        def _doc_clause() -> tuple[str, list[Any]]:
            return (" AND c.doc_id = ?", [doc_id]) if doc_id else ("", [])

        # 1. trigram FTS5
        _BOOL_OPS = {"OR", "AND", "NOT"}
        tokens = [t for t in query.split()
                  if len(t) >= 3 and t.upper() not in _BOOL_OPS]
        if not tokens and len(query.replace(" ", "")) >= 3:
            tokens = [query]
        if tokens:
            fts_query = " OR ".join(f'"{t}"' for t in tokens)
            doc_sql, doc_params = _doc_clause()
            sql = (
                "SELECT c.* FROM chunks_fts f JOIN chunks c ON c.chunk_id = f.chunk_id "
                "WHERE chunks_fts MATCH ?" + doc_sql + " LIMIT ?"
            )
            params: list[Any] = [fts_query, *doc_params, top_k]
            try:
                cur = self._conn.execute(sql, params)
                rows = [_row_to_dict(r) for r in cur.fetchall()]
                if rows:
                    return rows
            except sqlite3.OperationalError:
                pass

        # 2. LIKE 兜底
        doc_sql, doc_params = _doc_clause()
        sql = (
            "SELECT * FROM chunks WHERE (content LIKE ? OR title LIKE ?)"
            + doc_sql.replace("c.doc_id", "doc_id")
            + " LIMIT ?"
        )
        like_q = f"%{query}%"
        cur = self._conn.execute(sql, [like_q, like_q, *doc_params, top_k])
        return [_row_to_dict(r) for r in cur.fetchall()]

    # ---------- document cache ----------

    def get_document_cache(self, file_hash: str) -> dict | None:
        cur = self._conn.execute(
            "SELECT * FROM document_cache WHERE file_hash = ?",
            (file_hash,),
        )
        row = cur.fetchone()
        return _row_to_dict(row) if row else None

    def upsert_document_cache(
        self,
        *,
        file_hash: str,
        source_name: str,
        doc_id: str,
        parsed_with: str,
        converted_docx_path: str = "",
        cache_status: str = "ready",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO document_cache (
                    file_hash,
                    source_name,
                    doc_id,
                    parsed_with,
                    converted_docx_path,
                    cache_status,
                    created_at,
                    updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    COALESCE((SELECT created_at FROM document_cache WHERE file_hash = ?), CURRENT_TIMESTAMP),
                    CURRENT_TIMESTAMP
                )""",
                (
                    file_hash,
                    source_name,
                    doc_id,
                    parsed_with,
                    converted_docx_path,
                    cache_status,
                    file_hash,
                ),
            )

    # ---------- standards ----------

    def upsert_standard(
        self,
        clause_id: str,
        standard_name: str,
        clause_num: str,
        title: str,
        content: str,
        tags: list[str],
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO standards "
                "(id, standard_name, clause_num, title, content, tags) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    clause_id,
                    standard_name,
                    clause_num,
                    title,
                    content,
                    json.dumps(tags, ensure_ascii=False),
                ),
            )
            conn.execute("DELETE FROM standards_fts WHERE id = ?", (clause_id,))
            conn.execute(
                "INSERT INTO standards_fts (id, standard_name, title, content, tags) "
                "VALUES (?, ?, ?, ?, ?)",
                (clause_id, standard_name, title, content, " ".join(tags)),
            )

    def search_standards(
        self,
        query: str,
        standard_filter: list[str] | None = None,
        top_k: int = 3,
    ) -> list[dict]:
        """检索标准条款；trigram FTS5 命中率优先，LIKE 兜底短查询。"""
        params: list[Any]

        def _with_filter(sql: str, base_params: list[Any]) -> tuple[str, list[Any]]:
            if standard_filter:
                placeholders = ",".join(["?"] * len(standard_filter))
                sql += f" AND s.standard_name IN ({placeholders})"
                base_params.extend(standard_filter)
            sql += " LIMIT ?"
            base_params.append(top_k)
            return sql, base_params

        # 1. 先尝试 trigram FTS5（适合 ≥3 字符的查询；多 token 用 OR 拆分）
        fts_results: list[dict] = []
        # 提取 ≥3 字符的 token，用 OR 拼接
        _BOOL_OPS = {"OR", "AND", "NOT"}
        tokens = [t for t in query.split()
                  if len(t) >= 3 and t.upper() not in _BOOL_OPS]
        if not tokens and len(query.replace(" ", "")) >= 3:
            tokens = [query]
        if tokens:
            fts_query = " OR ".join(f'"{t}"' for t in tokens)
            sql = (
                "SELECT s.* FROM standards_fts f JOIN standards s ON s.id = f.id "
                "WHERE standards_fts MATCH ?"
            )
            params = [fts_query]
            sql, params = _with_filter(sql, params)
            try:
                cur = self._conn.execute(sql, params)
                fts_results = [_row_to_dict(r) for r in cur.fetchall()]
            except sqlite3.OperationalError:
                fts_results = []
        if fts_results:
            return fts_results

        # 2. LIKE 兜底（短查询或 FTS 未命中），用第一个 token 避免 OR 语法问题
        first_token = query.split()[0] if query.split() else query
        like_q = f"%{first_token}%"
        sql = (
            "SELECT s.* FROM standards s "
            "WHERE (s.content LIKE ? OR s.title LIKE ? OR s.tags LIKE ?)"
        )
        params = [like_q, like_q, like_q]
        sql, params = _with_filter(sql, params)
        try:
            cur = self._conn.execute(sql, params)
            return [_row_to_dict(r) for r in cur.fetchall()]
        except sqlite3.OperationalError:
            return []

    # ---------- labels ----------

    def upsert_label(
        self,
        *,
        label_id: str,
        doc_id: str,
        dimension: str,
        pipeline: str,
        final_verdict: str | None = None,
        score: int | None = None,
        confidence: int | None = None,
        explorer_a: dict | None = None,
        explorer_b: dict | None = None,
        critic: dict | None = None,
        findings: list[dict] | None = None,
        extra: dict | None = None,
        need_human_review: bool = False,
        human_signoff: bool = False,
    ) -> None:
        def _j(v: Any) -> str | None:
            return json.dumps(v, ensure_ascii=False) if v is not None else None

        with self.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO labels (
                    label_id, doc_id, dimension, pipeline,
                    explorer_a, explorer_b, critic,
                    final_verdict, score, confidence,
                    findings, extra,
                    need_human_review, human_signoff
                ) VALUES (?,?,?,?, ?,?,?, ?,?,?, ?,?, ?,?)""",
                (
                    label_id,
                    doc_id,
                    dimension,
                    pipeline,
                    _j(explorer_a),
                    _j(explorer_b),
                    _j(critic),
                    final_verdict,
                    score,
                    confidence,
                    _j(findings),
                    _j(extra),
                    1 if need_human_review else 0,
                    1 if human_signoff else 0,
                ),
            )

    def get_labels(
        self,
        doc_id: str,
        pipeline: str | None = None,
    ) -> list[dict]:
        if pipeline:
            cur = self._conn.execute(
                "SELECT * FROM labels WHERE doc_id = ? AND pipeline = ?",
                (doc_id, pipeline),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM labels WHERE doc_id = ?", (doc_id,)
            )
        return [_row_to_dict(r) for r in cur.fetchall()]


    # ---------- skills ----------

    def upsert_skill(
        self,
        skill_id: str,
        name: str,
        dimension: str,
        pattern: str,
        solution: str,
        example_in: str = "",
        example_out: str = "",
        tags: list[str] | None = None,
    ) -> None:
        import datetime as _dt
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        now = _dt.datetime.now().isoformat()
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO skills "
                "(skill_id, name, dimension, pattern, solution, example_in, example_out, created_at, tags) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (skill_id, name, dimension, pattern, solution, example_in, example_out, now, tags_json),
            )
            cur2 = self._conn.execute(
                "SELECT rowid FROM skills_fts WHERE skill_id = ?", (skill_id,)
            )
            old = cur2.fetchone()
            if old:
                conn.execute("DELETE FROM skills_fts WHERE rowid = ?", (old[0],))
            conn.execute(
                "INSERT INTO skills_fts (skill_id, name, dimension, pattern, solution, tags) "
                "VALUES (?,?,?,?,?,?)",
                (skill_id, name, dimension, pattern, solution, " ".join(tags or [])),
            )

    def search_skills(
        self,
        query: str,
        dimension: str | None = None,
        top_k: int = 3,
    ) -> list[dict]:
        params: list[Any]
        fts_results: list[dict] = []
        tokens = [t for t in query.split() if len(t) >= 2]
        if not tokens and query.strip():
            tokens = [query.strip()]
        if tokens:
            fts_q = " OR ".join(f'"{t}"' for t in tokens[:8])
            if dimension:
                sql = (
                    "SELECT s.* FROM skills_fts f JOIN skills s ON s.skill_id = f.skill_id "
                    "WHERE skills_fts MATCH ? AND s.dimension = ? LIMIT ?"
                )
                params = [fts_q, dimension, top_k]
            else:
                sql = (
                    "SELECT s.* FROM skills_fts f JOIN skills s ON s.skill_id = f.skill_id "
                    "WHERE skills_fts MATCH ? LIMIT ?"
                )
                params = [fts_q, top_k]
            try:
                cur = self._conn.execute(sql, params)
                fts_results = [_row_to_dict(r) for r in cur.fetchall()]
            except Exception:
                fts_results = []
        if fts_results:
            return fts_results
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
        return [_row_to_dict(r) for r in cur.fetchall()]

    def increment_skill_usage(self, skill_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE skills SET used_count = used_count + 1 WHERE skill_id = ?",
                (skill_id,),
            )

    # ---------- standard_versions ----------

    def get_standard_version(self, number_normalized: str) -> dict | None:
        cur = self._conn.execute(
            "SELECT * FROM standard_versions WHERE number_normalized = ?",
            (number_normalized,),
        )
        row = cur.fetchone()
        return _row_to_dict(row) if row else None

    def upsert_standard_version(
        self,
        *,
        number_normalized: str,
        number_raw: str,
        latest_year: int | None = None,
        title: str = "",
        status: str = "current",
        superseded_by: str | None = None,
        search_snippets: list[str] | None = None,
        source: str = "manual",
        fetched_at: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO standard_versions
                   (number_normalized, number_raw, latest_year, title, status,
                    superseded_by, search_snippets, source, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    number_normalized,
                    number_raw,
                    latest_year,
                    title,
                    status,
                    superseded_by,
                    json.dumps(search_snippets, ensure_ascii=False) if search_snippets else None,
                    source,
                    fetched_at,
                ),
            )


def _row_to_dict(row: sqlite3.Row | None) -> dict:
    if row is None:
        return {}
    out = dict(row)
    for k in ("dimensions", "cross_refs", "extra", "tags",
              "explorer_a", "explorer_b", "critic", "findings"):
        if k in out and isinstance(out[k], str) and out[k]:
            try:
                out[k] = json.loads(out[k])
            except json.JSONDecodeError:
                pass
    return out
