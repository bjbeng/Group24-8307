"""混合检索：BM25(FTS5) + Dense(ChromaDB) + RRF 融合。

设计说明：
- FTS5（BM25）路径：查 SQLite standards 表，返回标准化条款文本（md_importer 切分）
- Dense 路径：查场景一标准文件 chunk 的 ChromaDB，返回原始标准文本（更多覆盖）
- 两路 top-k 结果合并后按 RRF 权重输出最终排名
- 任一路失败均静默降级，不影响审核流程
"""
from __future__ import annotations

import logging
import math
import os
import re
from pathlib import Path
from typing import Any

from src.store.repository import Repository

log = logging.getLogger(__name__)

# RRF 参数：k 越大排名靠后的结果权重越平滑
_RRF_K = 60
_BM25_TOP_K = 10
_DENSE_TOP_K = 10
_FINAL_TOP_K = 5


def _resolve_chroma_path() -> Path:
    """解析 ChromaDB 路径，优先级：
    1. CHROMA_DB_PATH 环境变量
    2. config default.yaml 的 paths.chroma_db_path
    3. 默认：backend/chroma_db
    """
    env_path = os.environ.get("CHROMA_DB_PATH", "")
    if env_path:
        return Path(env_path)
    # parents: [standards_lib, src, backend/chroma_db]
    return Path(__file__).resolve().parents[1] / "chroma_db"


# ChromaDB 里实际存在的 8 个 source（文件名前缀），按维度分组。
# 空列表 = 该维度不过滤（所有 source 都参与）。
# 过滤逻辑：source 字段包含列表中任意一个子串即保留。
_DIM_DENSE_SOURCE_FILTERS: dict[str, list[str]] = {
    "C2_content_completeness": [
        "GB_50251",   # 输气管道工程设计规范 — 技术参数基准
        "GB_50253",   # 输油管道工程设计规范 — 技术参数基准
        "SYT5922",    # 天然气管道运行规范 — 操作规程/岗位职责
        "GB-21447",   # 钢质管道外腐蚀控制 — 技术参数
        "GB-21448",   # 埋地管道阴极保护 — 技术参数
    ],
    "C5_logic": [
        "GB_50251", "GB_50253", "SYT5922",
    ],
    "E1_staffing": [
        "SYT5922",    # 运行规范含岗位与培训要求
    ],
    "E2_emergency": [
        "SYT5922",    # 运行规范含应急处置章节
    ],
    "L2_standards": [],  # 不限（任何标准都可能被引用）
    "C1_structure": [],
    "C3_language": [],
    "C4_reference": [],
}

# Dense 过滤后最少保留条数；不足时回退到不过滤
_DENSE_FILTER_MIN = 2


class HybridSearcher:
    def __init__(self, repo: Repository | None = None) -> None:
        self.repo = repo

    # ── Dense (ChromaDB) ───────────────────────────────────────────────────

    def _dense_search(
        self,
        query_text: str,
        top_k: int = _DENSE_TOP_K,
        dimension: str = "",
    ) -> list[dict[str, Any]]:
        """用 bge-m3 embed query，查 ChromaDB cosine。

        dimension 非空时：先拉 top_k*2 条，再按 _DIM_DENSE_SOURCE_FILTERS 对 source
        字段做子串过滤，保留相关标准；过滤后不足 _DENSE_FILTER_MIN 条则回退到不过滤结果。
        """
        try:
            import chromadb
            from src.standards_lib.embedder import get_embedder
            embedder = get_embedder()
            query_vec = embedder.encode_query(query_text)
            chroma_path = _resolve_chroma_path()
            client = chromadb.PersistentClient(path=str(chroma_path.resolve()))
            col = client.get_collection("pipeline_specs")

            source_kws = _DIM_DENSE_SOURCE_FILTERS.get(dimension, []) if dimension else []
            fetch_k = top_k * 2 if source_kws else top_k

            results = col.query(
                query_embeddings=[query_vec.tolist()],
                n_results=min(fetch_k, col.count()),
                include=["documents", "metadatas", "distances"],
            )
            rows = [
                {
                    "id":       results["ids"][0][i],
                    "content":  results["documents"][0][i],
                    "distance": results["distances"][0][i],
                    "meta":     results["metadatas"][0][i],
                }
                for i in range(len(results["ids"][0]))
            ]

            if source_kws:
                filtered = [
                    r for r in rows
                    if any(kw in r["meta"].get("source", "") for kw in source_kws)
                ]
                if len(filtered) >= _DENSE_FILTER_MIN:
                    rows = filtered[:top_k]
                    log.debug(
                        "Dense 过滤后 %d 条（dim=%s, query='%s'）",
                        len(rows), dimension, query_text[:30],
                    )
                else:
                    rows = rows[:top_k]
                    log.debug(
                        "Dense 过滤结果不足 %d 条，回退全量（dim=%s）",
                        _DENSE_FILTER_MIN, dimension,
                    )
            else:
                rows = rows[:top_k]
                log.debug("Dense 检索命中 %d 条（query='%s'）", len(rows), query_text[:30])

            return rows
        except Exception as e:
            log.warning("Dense 检索失败: %s", e)
            return []

    # ── BM25 (FTS5) ─────────────────────────────────────────────────────

    def _bm25_search(
        self,
        query: str,
        top_k: int = _BM25_TOP_K,
        dimension: str = "",
    ) -> list[dict[str, Any]]:
        """用 FTS5 检索 standards 表；dimension 非空时限定白名单标准。"""
        if not self.repo:
            return []
        try:
            if dimension:
                from src.retrieve.fts_search import search_standards_for_dimension
                rows = search_standards_for_dimension(self.repo, dimension, query, top_k=top_k)
            else:
                tokens = [t.strip() for t in re.split(r'\s+', query) if len(t.strip()) >= 2]
                if not tokens:
                    tokens = [query]
                fts_q = " OR ".join(f'"{t}"' for t in tokens[:6])
                rows = self.repo.search_standards(query=fts_q, top_k=top_k)
            log.debug("BM25 检索命中 %d 条（query='%s'）", len(rows), query[:30])
            return rows
        except Exception as e:
            log.warning("BM25 检索失败: %s", e)
            return []

    # ── RRF 融合 ─────────────────────────────────────────────────────────

    @staticmethod
    def _rrf_fuse(
        bm25_rows: list[dict[str, Any]],
        dense_rows: list[dict[str, Any]],
        k: float = _RRF_K,
    ) -> list[dict[str, Any]]:
        """Reciprocal Rank Fusion：按排名倒数加权合并两路结果。"""
        scores: dict[str, float] = {}
        seen: dict[str, dict[str, Any]] = {}

        def _add_rows(rows: list[dict[str, Any]], weight: float) -> None:
            for rank, row in enumerate(rows, start=1):
                key = str(row.get("id", row.get("clause_id", row.get("number_raw", ""))))
                scores[key] = scores.get(key, 0) + weight / (k + rank)
                if key not in seen:
                    seen[key] = dict(row)

        _add_rows(bm25_rows, 1.0)
        _add_rows(dense_rows, 1.0)

        sorted_keys = sorted(scores, key=lambda k: scores[k], reverse=True)
        result = []
        for key in sorted_keys:
            row = dict(seen[key])
            row["rrf_score"] = scores[key]
            result.append(row)

        return result

    # ── 主入口 ────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        *,
        top_k: int = _FINAL_TOP_K,
        bm25_top: int = _BM25_TOP_K,
        dense_top: int = _DENSE_TOP_K,
        dimension: str = "",
    ) -> list[dict[str, Any]]:
        """两路并行检索 + RRF 融合，返回 top_k 条最终结果。"""
        bm25_rows = self._bm25_search(query, top_k=bm25_top, dimension=dimension)
        dense_rows = self._dense_search(query, top_k=dense_top, dimension=dimension)

        if not bm25_rows and not dense_rows:
            log.debug("HybridSearch: 两路均无结果（query='%s'）", query[:40])
            return []

        if not bm25_rows:
            return dense_rows[:top_k]
        if not dense_rows:
            return bm25_rows[:top_k]

        fused = self._rrf_fuse(bm25_rows, dense_rows)
        return fused[:top_k]

    def search_for_agent(
        self,
        query: str,
        dimension: str,
        top_k: int = _FINAL_TOP_K,
    ) -> list[dict[str, Any]]:
        """供 Agent 调用的封装入口，自动按 dimension 限定 FTS5 白名单。"""
        return self.search(query=query, top_k=top_k, dimension=dimension)


# ── 便利函数 ──────────────────────────────────────────────────────────────

_HYBRID_CACHE: dict[str, "HybridSearcher"] = {}


def get_hybrid_searcher(user_id: str = "") -> HybridSearcher:
    """按 user_id 缓存 HybridSearcher。"""
    if user_id not in _HYBRID_CACHE:
        from src.store.repository import get_repository
        repo = get_repository(user_id) if user_id else None
        _HYBRID_CACHE[user_id] = HybridSearcher(repo=repo)
    return _HYBRID_CACHE[user_id]