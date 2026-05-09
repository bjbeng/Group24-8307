"""FTS + LLM 类维度的公共工具。"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any

from src.agents.base import AgentResult, Finding
from src.retrieve.fts_search import search_standards_for_dimension
from src.store.repository import Repository


@dataclass
class ChunkRef:
    """一个 chunk 的引用，包含原始 metadata + 截断文本。"""
    chunk_id: str
    section_path: str
    page_start: int
    page_end: int
    bbox: list[float] = field(default_factory=list)
    chunk_type: str = "TEXT"
    excerpt: str = ""
    is_key_chunk: bool = False
    heading_level: int | None = None
    anchor_text: str = ""


log = logging.getLogger(__name__)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default

# 各维度 excerpt 关键词（粗筛相关段落）
C2_KEYWORDS = (
    "职责", "岗位", "操作", "规程", "技术", "参数", "管道", "应急",
    "培训", "HSE", "QHSE", "安全", "环保", "标准", "作业",
    "处置", "处置卡", "应急处置", "应急流程", "预案",
    "压力", "温度", "里程", "MPa", "版本", "引用", "现行",
)
E2_KEYWORDS = (
    "应急", "处置", "事故", "泄漏", "抢险", "预案", "报告", "疏散",
    "警戒", "现场", "响应",
)
C5_KEYWORDS = (
    "压力", "温度", "里程", "MPa", "kPa", "兆帕", "公里", "米",
    "时间", "年月", "日期", "编制", "批准", "审核",
    "附件", "图", "表", "附录", "前", "后", "一致", "矛盾",
    "应", "不得", "禁止", "必须",
)
C3_KEYWORDS = (
    "标点", "语句", "通顺", "错别字", "缩略词", "注释",
    "HSE", "QHS", "MPa", "kPa", "psi", "规范", "文字", "格式",
)
L2_KEYWORDS = (
    "标准", "GB", "QSY", "TSG", "AQ", "引用", "版本", "依据",
    "管道", "压力", "里程", "完整性",
)
E1_KEYWORDS = (
    "员工", "人员", "工程师", "区段", "巡线", "管道", "里程",
    "配置", "配备", "HSE", "安全", "专职", "岗位",
)


def collect_chunks(
    chunks: list[dict[str, Any]],
    keywords: tuple[str, ...] | None,
    chunk_types: tuple[str, ...] | None,
    *,
    max_chars: int = 6000,
    max_chunks: int = 40,
    seed: int = 42,
) -> list[ChunkRef]:
    """按类型过滤 → 关键词命中 → 随机抽样 → 截断，返回结构化 ChunkRef 列表。

    优先保留关键词命中的 chunk，不足时从其余 chunk 中随机补充。
    所有坐标信息（bbox、page_start、page_end、section_path）均保留在 ChunkRef 中。
    """
    rng = random.Random(seed)

    # 1. 类型过滤（优先于关键词）
    candidates: list[dict[str, Any]] = chunks
    if chunk_types:
        types_lower = tuple(t.lower() for t in chunk_types)
        candidates = [c for c in candidates if c.get("chunk_type", "").lower() in types_lower]

    # 2. 分离关键词命中 vs 其余
    hit: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    for c in candidates:
        text = (c.get("content") or "").strip()
        if not text:
            continue
        is_key = keywords is None or any(kw in text for kw in keywords)
        if is_key:
            hit.append(c)
        else:
            rest.append(c)

    # 3. 随机打乱（用 seed 保证可复现）
    rng.shuffle(hit)
    rng.shuffle(rest)

    # 4. 优先取命中，不足则从其余补充
    ordered = hit[:max_chunks] + rest[: max(0, max_chunks - len(hit))]

    # 5. 截断并构建 ChunkRef
    result: list[ChunkRef] = []
    total_len = 0
    for c in ordered:
        text = (c.get("content") or "").strip()
        excerpt = text
        # 按 max_chars 上界截断（保留完整句子可进一步优化）
        if len(excerpt) > max_chars:
            excerpt = excerpt[:max_chars]

        if total_len + len(excerpt) + 1 > max_chars and result:
            break
        total_len += len(excerpt) + 1

        # 判断是否是关键词命中（用原始 text，不是截断后的）
        is_key_chunk = bool(keywords) and any(kw in text for kw in keywords)

        # 解析 heading_level
        heading_level: int | None = None
        if c.get("chunk_type", "").lower() == "heading":
            level = c.get("heading_level")
            if isinstance(level, int):
                heading_level = level

        # 解析 bbox（可能是 JSON 字符串或 list[float]）
        raw_bbox = c.get("bbox", [])
        if isinstance(raw_bbox, str):
            import json
            try:
                bbox = json.loads(raw_bbox)
            except (json.JSONDecodeError, TypeError):
                bbox = []
        elif isinstance(raw_bbox, list):
            bbox = raw_bbox
        else:
            bbox = []

        result.append(
            ChunkRef(
                chunk_id=str(c.get("chunk_id", "")),
                section_path=str(c.get("section_path", "")),
                page_start=_safe_int(c.get("page_start", 0), 0),
                page_end=_safe_int(c.get("page_end", 0), 0),
                bbox=bbox,
                chunk_type=str(c.get("chunk_type", "TEXT")),
                excerpt=excerpt,
                is_key_chunk=is_key_chunk,
                heading_level=heading_level,
                anchor_text=text[:80] if text else "",
            )
        )
    return result


def collect_chunks_all(
    chunks: list[dict[str, Any]],
    chunk_types: tuple[str, ...],
    *,
    seed: int = 42,
) -> list[ChunkRef]:
    """收集所有匹配类型的 ChunkRef（不过滤、不抽样、不限制字符数）。

    用于全文检查场景（如 C3 语言规范需要扫描全部正文）。
    所有坐标信息（bbox、page_start、page_end、section_path、anchor_text）均保留。
    """
    rng = random.Random(seed)

    # 1. 类型过滤
    candidates: list[dict[str, Any]] = chunks
    types_lower = tuple(t.lower() for t in chunk_types)
    candidates = [c for c in candidates if c.get("chunk_type", "").lower() in types_lower]

    # 2. 随机打乱（seed 保证可复现）
    rng.shuffle(candidates)

    # 3. 构建 ChunkRef
    result: list[ChunkRef] = []
    for c in candidates:
        text = (c.get("content") or "").strip()
        if not text:
            continue

        # 解析 heading_level
        heading_level: int | None = None
        if c.get("chunk_type", "").lower() == "heading":
            level = c.get("heading_level")
            if isinstance(level, int):
                heading_level = level

        # 解析 bbox（可能是 JSON 字符串或 list[float]）
        raw_bbox = c.get("bbox", [])
        if isinstance(raw_bbox, str):
            import json
            try:
                bbox = json.loads(raw_bbox)
            except (json.JSONDecodeError, TypeError):
                bbox = []
        elif isinstance(raw_bbox, list):
            bbox = raw_bbox
        else:
            bbox = []

        result.append(
            ChunkRef(
                chunk_id=str(c.get("chunk_id", "")),
                section_path=str(c.get("section_path", "")),
                page_start=_safe_int(c.get("page_start", 0), 0),
                page_end=_safe_int(c.get("page_end", 0), 0),
                bbox=bbox,
                chunk_type=str(c.get("chunk_type", "TEXT")),
                excerpt=text,
                is_key_chunk=False,
                heading_level=heading_level,
                anchor_text=text[:80] if text else "",
            )
        )
    return result


def _build_chunk_refs_from_rows(rows: list[dict[str, Any]]) -> list[ChunkRef]:
    """将 to_row() 输出的 dict 列表转换为 ChunkRef 列表（供内部批量使用）。"""
    result: list[ChunkRef] = []
    for c in rows:
        text = (c.get("content") or "").strip()
        raw_bbox = c.get("bbox", [])
        if isinstance(raw_bbox, str):
            import json
            try:
                bbox = json.loads(raw_bbox)
            except (json.JSONDecodeError, TypeError):
                bbox = []
        elif isinstance(raw_bbox, list):
            bbox = raw_bbox
        else:
            bbox = []
        result.append(
            ChunkRef(
                chunk_id=str(c.get("chunk_id", "")),
                section_path=str(c.get("section_path", "")),
                page_start=_safe_int(c.get("page_start", 0), 0),
                page_end=_safe_int(c.get("page_end", 0), 0),
                bbox=bbox,
                chunk_type=str(c.get("chunk_type", "TEXT")),
                excerpt=text,
                is_key_chunk=False,
                heading_level=c.get("heading_level"),
                anchor_text=text[:80] if text else "",
            )
        )
    return result


def collect_excerpt(
    chunks: list[dict[str, Any]],
    keywords: tuple[str, ...],
    *,
    max_chars: int = 6000,
    max_chunks: int = 40,
    seed: int = 42,
) -> str:
    """废弃：请用 collect_chunks()。

    保留向后兼容，返回纯文本拼接。
    """
    refs = collect_chunks(chunks, keywords, None, max_chars=max_chars, max_chunks=max_chunks, seed=seed)
    return "\n---\n".join(r.excerpt for r in refs if r.excerpt.strip())


def retrieve_standard_snippets(
    repo: Repository | None,
    dimension: str,
    query: str,
    *,
    top_k: int = 5,
    use_hybrid: bool = True,
    user_id: str = "",
) -> list[dict[str, Any]]:
    """FTS5 检索 + 混合检索（ChromaDB Dense + FTS5 BM25 + RRF）。

    use_hybrid=True 时：优先用 HybridSearcher，并行查两路后 RRF 融合。
    use_hybrid=False 时：纯 FTS5（向后兼容）。

    注意：HybridSearcher 通过 get_hybrid_searcher() 缓存复用，避免重复加载 embedding 模型。
    """
    if not query.strip():
        return []
    try:
        if use_hybrid and repo is not None:
            from src.standards_lib.hybrid_search import get_hybrid_searcher
            searcher = get_hybrid_searcher(user_id=user_id)
            rows = searcher.search(query=query, top_k=top_k)
            if rows:
                log.debug("混合检索命中 %d 条（query='%s'）", len(rows), query[:40])
                return rows
            # 降级到纯 FTS5
            log.debug("混合检索无结果，降级为 FTS5")
        if repo is not None:
            return search_standards_for_dimension(repo, dimension, query, top_k=top_k)
    except Exception as e:
        log.warning("%s 标准检索失败: %s", dimension, e)
    return []


def format_snippets_for_prompt(rows: list[dict[str, Any]]) -> str:
    """统一格式化检索结果，支持两种行格式：
    - FTS5 行：含 standard_name / clause_num / title / content
    - ChromaDB 行（hybrid）：含 content / meta（meta.source 是标准文件名）
    """
    if not rows:
        return "（无检索结果）"
    blocks = []
    for r in rows:
        # FTS5 行（md_importer 导入的）
        if "standard_name" in r:
            blocks.append(
                f"- [{r.get('standard_name', '')} {r.get('clause_num', '')}] "
                f"{r.get('title', '')}\n  {r.get('content', '')}"
            )
        else:
            # ChromaDB 行（原始场景一标准文件 chunk）
            meta = r.get("meta") or {}
            src = meta.get("source", "")
            chapter = meta.get("chapter", "")
            label = chapter if chapter else (src.split("_")[1] if "_" in src else src[:20])
            blocks.append(
                f"- [标准摘录] {label}\n  {r.get('content', '')[:300]}"
            )
    return "\n".join(blocks)


def build_section_toc(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从 chunks 构建目录树（给前端用）。

    返回格式：
    [
        {"section_path": "1", "title": "前言", "page": 4, "level": 1},
        {"section_path": "2", "title": "1  岗位设置", "page": 4, "level": 1},
        {"section_path": "2.1", "title": "2.1  1.1  站场通用设计", "page": 5, "level": 2},
        ...
    ]
    """
    # 从 chunk_type="HEADING" 的 chunks 提取
    headings: list[dict[str, Any]] = []
    for c in chunks:
        if c.get("chunk_type", "").upper() != "HEADING":
            continue
        content = c.get("content", "") or c.get("title", "") or ""
        if not content.strip():
            continue
        section_path = c.get("section_path", "")
        page = c.get("page_start", 0)
        # level 从 heading_level 或从 section_path 推断
        level = c.get("heading_level")
        if level is None:
            level = section_path.count(".") + 1 if section_path else 1
        headings.append({
            "section_path": section_path,
            "title": content.strip(),
            "page": page,
            "level": level,
        })

    # 按 section_path 排序（自然排序）
    def _natural_key(item: dict[str, Any]) -> tuple[tuple[int, ...], str]:
        path = item["section_path"]
        if not path:
            return ((), path)
        parts = path.split(".")
        nums = tuple(int(p) for p in parts if p.isdigit())
        return (nums, path)

    headings.sort(key=_natural_key)
    return headings


def _dimension_to_category(dimension: str) -> str:
    """根据维度名推断审核分类，用于报告组织。"""
    if dimension in (
        "C1_structure",
        "C2_content_completeness",
        "C3_language",
        "C4_reference",
        "C5_logic",
    ):
        return "content"
    if dimension in ("E1_staffing", "E2_emergency"):
        return "deep"
    if dimension == "T1_template":
        return "template"
    return ""


def agent_result_from_llm_json(
    data: dict[str, Any],
    *,
    dimension: str,
    max_score: int = 12,
    default_details: str = "",
) -> AgentResult:
    """将 LLM JSON 规范化为 AgentResult。"""
    verdict = str(data.get("verdict", "uncertain")).lower()
    if verdict not in ("pass", "partial", "fail", "uncertain"):
        verdict = "uncertain"

    try:
        score = int(data.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(max_score, score))

    try:
        confidence = int(data.get("confidence", 70))
    except (TypeError, ValueError):
        confidence = 70
    confidence = max(0, min(100, confidence))

    cat = _dimension_to_category(dimension)
    findings: list[Finding] = []
    for item in data.get("findings", []) or []:
        if not isinstance(item, dict):
            continue
        findings.append(
            Finding(
                severity=str(item.get("severity", "medium")),
                description=str(item.get("description", "")),
                evidence=str(item.get("evidence", "")),
                rule_id=item.get("rule_id"),
                chunk_id=item.get("chunk_id"),
                category=cat,
                is_problem=item.get("is_problem", True),
                problem_type=str(item.get("problem_type", "")),
                rule_basis=str(item.get("rule_basis", "")),
                correction_suggestion=str(item.get("correction_suggestion", "")),
            )
        )

    details = str(data.get("details", "") or default_details)
    extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
    need_human = bool(data.get("need_human_review", False)) or verdict == "uncertain"

    return AgentResult(
        dimension=dimension,
        verdict=verdict,
        score=score,
        confidence=confidence,
        findings=findings,
        details=details,
        extra=extra,
        need_human_review=need_human,
    )


def build_json_only_system(task_brief: str) -> str:
    return (
        f"{task_brief}\n\n"
        "只输出一个 JSON 对象，不要用 markdown 围栏。字段：\n"
        '{"verdict":"pass|partial|fail|uncertain","score":0-12,"confidence":0-100,'
        '"details":"一句话摘要",'
        '"findings":[{"severity":"high|medium|low","description":"","evidence":"","rule_id":""}],'
        '"extra":{}}\n'
    )
