"""标准版本 Web 检索：DuckDuckGo 搜索 + SQLite 缓存。

职责：
  对文档中提取出的每个标准号，查本地缓存；未命中则 DuckDuckGo 搜索，
  把 top-3 摘要片段写回缓存（TTL=30天），供 LLM 比对。

LLM 收到的是原始搜索片段，不是这里的判断——判断由 LLM 自己做。
"""
from __future__ import annotations

import datetime
import json
import logging
from dataclasses import dataclass
from typing import Any

from src.store.repository import Repository
from src.standards_lib.normalizer import Citation

log = logging.getLogger(__name__)

# 搜索缓存 TTL（天）；过期则重新搜
_CACHE_TTL_DAYS = 30
# 每个标准号最多返回几条摘要片段给 LLM
_MAX_SNIPPETS = 3


@dataclass
class VersionContext:
    """一个标准号的版本核查上下文，交给 LLM 比对用。"""
    number_raw: str          # 文档中的原始写法，如 "TSG 31-2009"
    cited_year: int | None   # 文档中引用的年份
    snippets: list[str]      # web 搜索结果摘要（空=搜索失败）
    from_cache: bool         # True=本地缓存命中


def _is_cache_fresh(fetched_at: str | None) -> bool:
    if not fetched_at:
        return False
    try:
        ts = datetime.datetime.fromisoformat(fetched_at)
        return (datetime.datetime.now() - ts).days < _CACHE_TTL_DAYS
    except ValueError:
        return False


def _ddg_search(query: str, max_results: int = _MAX_SNIPPETS) -> list[str]:
    """用 DuckDuckGo 搜索，返回 top-N 摘要片段（title + body）。失败返回空列表。"""
    try:
        from ddgs import DDGS
        results = DDGS().text(query, max_results=max_results, region="cn-zh")
        snippets = []
        for r in results or []:
            title = r.get("title", "")
            body = r.get("body", "")
            snippets.append(f"{title}｜{body[:200]}" if title else body[:200])
        return snippets
    except Exception as e:
        log.warning("DuckDuckGo 搜索失败（query='%s'）: %s", query, e)
        return []


def fetch_version_context(
    citation: Citation,
    repo: Repository,
) -> VersionContext:
    """取一个标准号的版本上下文：先查缓存，未命中则 web 搜索。"""
    norm = citation.number_normalized

    # 1. 命中本地缓存（标准年份已知且缓存未过期）
    row = repo.get_standard_version(norm)
    if row and _is_cache_fresh(row.get("fetched_at")):
        snippets_raw = row.get("search_snippets") or []
        if isinstance(snippets_raw, str):
            try:
                snippets_raw = json.loads(snippets_raw)
            except Exception:
                snippets_raw = []
        return VersionContext(
            number_raw=citation.number_raw,
            cited_year=citation.year,
            snippets=snippets_raw,
            from_cache=True,
        )

    # 2. 缓存未命中 / 已过期 → web 搜索
    current_year = datetime.datetime.now().year
    query = f"{citation.number_raw} 最新版本 现行有效 {current_year}"
    snippets = _ddg_search(query)

    # 3. 写回缓存
    fetched_at = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        repo.upsert_standard_version(
            number_normalized=norm,
            number_raw=citation.number_raw,
            latest_year=row.get("latest_year") if row else None,
            title=row.get("title", "") if row else "",
            status=row.get("status", "unknown") if row else "unknown",
            superseded_by=row.get("superseded_by") if row else None,
            search_snippets=snippets,
            source="web",
            fetched_at=fetched_at,
        )
    except Exception as e:
        log.warning("写回标准版本缓存失败（%s）: %s", norm, e)

    return VersionContext(
        number_raw=citation.number_raw,
        cited_year=citation.year,
        snippets=snippets,
        from_cache=False,
    )


def fetch_all_version_contexts(
    citations: list[Citation],
    repo: Repository,
    *,
    max_citations: int = 8,
) -> list[VersionContext]:
    """批量取版本上下文；最多处理 max_citations 个（避免搜索太多拖慢审核）。"""
    seen: set[str] = set()
    results: list[VersionContext] = []
    for cit in citations:
        if cit.number_normalized in seen:
            continue
        seen.add(cit.number_normalized)
        ctx = fetch_version_context(cit, repo)
        results.append(ctx)
        if len(results) >= max_citations:
            break
    return results


def format_version_contexts_for_prompt(contexts: list[VersionContext]) -> str:
    """把版本上下文列表格式化为 LLM prompt 片段。"""
    if not contexts:
        return "（无可用标准版本参考信息）"

    lines = ["## 标准版本参考信息（来自网络搜索，供核实引用是否为最新版）\n"]
    for ctx in contexts:
        year_str = f"（文档引用年份：{ctx.cited_year}）" if ctx.cited_year else "（文档未注年份）"
        cache_tag = "[缓存]" if ctx.from_cache else "[实时搜索]"
        lines.append(f"### {ctx.number_raw} {year_str} {cache_tag}")
        if ctx.snippets:
            for i, s in enumerate(ctx.snippets, 1):
                lines.append(f"  {i}. {s}")
        else:
            lines.append("  （未找到相关搜索结果）")
        lines.append("")

    return "\n".join(lines)
