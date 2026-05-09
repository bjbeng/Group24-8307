"""检索类工具：FTS 搜索、chunk 获取、cross-ref 追踪。"""
from __future__ import annotations
from typing import Any, TYPE_CHECKING
from .registry import tool
if TYPE_CHECKING:
    from src.store.repository import Repository

_repo: "Repository | None" = None

def set_repo(repo: "Repository") -> None:
    global _repo
    _repo = repo

def _get_repo() -> "Repository":
    if _repo is None:
        raise RuntimeError("Repository 未初始化，先调用 set_repo()")
    return _repo

@tool("fts_search", "在国标/企标库里全文检索相关条款")
def fts_search(query: str, dimension: str, top_k: int = 5) -> list[dict[str, Any]]:
    from src.retrieve.fts_search import search_standards_for_dimension
    return search_standards_for_dimension(_get_repo(), dimension, query, top_k=top_k)

@tool("get_chunks_by_dimension", "按维度白名单拉取文档 chunks")
def get_chunks_by_dimension(doc_id: str, dimension: str) -> list[dict[str, Any]]:
    return _get_repo().get_chunks_by_dimension(doc_id, dimension)

@tool("get_chunk_by_id", "精确按 chunk_id 取完整内容")
def get_chunk_by_id(chunk_id: str) -> dict[str, Any] | None:
    return _get_repo().get_chunk(chunk_id)

@tool("get_appendix", "按附录标号取内容，如 get_appendix(doc_id='ASZYQ', label='C')")
def get_appendix(doc_id: str, label: str) -> dict[str, Any] | None:
    chunks = _get_repo().get_chunks_by_doc(doc_id)
    label_upper = label.upper()
    for c in chunks:
        if c.get("chunk_type") in ("appendix",):
            extra = c.get("extra") or {}
            if isinstance(extra, dict) and extra.get("appendix_id", "").upper() == label_upper:
                return c
        title = (c.get("title") or "").upper()
        if f"附录{label_upper}" in title or f"APPENDIX {label_upper}" in title:
            return c
    return None

@tool("cross_ref_lookup", "顺着 cross_refs_to 取出被引用的 chunks")
def cross_ref_lookup(source_chunk_id: str) -> list[dict[str, Any]]:
    import json
    repo = _get_repo()
    src = repo.get_chunk(source_chunk_id)
    if not src:
        return []
    refs = src.get("cross_refs") or []
    if isinstance(refs, str):
        try:
            refs = json.loads(refs)
        except Exception:
            return []
    results = []
    for ref_id in refs:
        c = repo.get_chunk(str(ref_id))
        if c:
            results.append(c)
    return results

@tool("search_chunks", "在文档 chunks 里全文检索")
def search_chunks(query: str, doc_id: str | None = None, top_k: int = 10) -> list[dict[str, Any]]:
    return _get_repo().search_chunks(query, doc_id=doc_id, top_k=top_k)
