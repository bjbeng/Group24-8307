"""DimContext 构建器：按维度拉取 chunks + 标准条款，做 token 预算管理。"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.store.repository import Repository

log = logging.getLogger(__name__)

@dataclass
class TokenBudget:
    system: int = 800
    chunks: int = 2500
    standards: int = 2000
    output: int = 1000

    @property
    def total(self) -> int:
        return self.system + self.chunks + self.standards + self.output

# 每维度独立预算（单位：字符，1 token ≈ 1.5 中文字符）
CONTEXT_BUDGETS: dict[str, TokenBudget] = {
    "C1_structure":             TokenBudget(chunks=3000, standards=1000),
    "C2_content_completeness":  TokenBudget(chunks=3000, standards=3000),
    "C3_language":              TokenBudget(chunks=2500, standards=2000),
    "C4_reference":             TokenBudget(chunks=3000, standards=1500),
    "C5_logic":                 TokenBudget(chunks=4000, standards=1500),
    "E1_staffing":              TokenBudget(chunks=2000, standards=1000),
    "E2_emergency":             TokenBudget(chunks=3000, standards=2500),
    "L2_standards":             TokenBudget(chunks=2500, standards=3000),
}
_DEFAULT_BUDGET = TokenBudget()

@dataclass
class DimContext:
    dimension: str
    doc_id: str
    chunks: list[dict[str, Any]] = field(default_factory=list)
    standards: list[dict[str, Any]] = field(default_factory=list)
    skills: list[dict[str, Any]] = field(default_factory=list)
    budget: TokenBudget = field(default_factory=TokenBudget)
    truncated: bool = False

    def chunks_text(self) -> str:
        parts = []
        for c in self.chunks:
            title = c.get("title", "")
            content = c.get("content", "")
            if title:
                parts.append(f"### {title}\n{content}")
            else:
                parts.append(content)
        return "\n---\n".join(parts)

    def standards_text(self) -> str:
        parts = []
        for s in self.standards:
            parts.append(
                f"- [{s.get('standard_name','')} {s.get('clause_num','')}] "
                f"{s.get('title','')}\n  {s.get('content','')}"
            )
        return "\n".join(parts) if parts else "（无相关标准条款）"

    def skills_text(self) -> str:
        if not self.skills:
            return ""
        parts = ["## 可参考的历史技能"]
        for sk in self.skills:
            parts.append(f"**{sk.get('name','')}**: {sk.get('solution','')[:400]}")
        return "\n".join(parts)

def _truncate_list_to_budget(items: list[dict[str, Any]], budget_chars: int, key: str = "content") -> tuple[list[dict[str, Any]], bool]:
    """按字符预算截断列表，返回 (截断后列表, 是否发生截断)。"""
    used = 0
    result = []
    truncated = False
    for item in items:
        text = item.get(key, "") or ""
        if used + len(text) > budget_chars:
            truncated = True
            break
        result.append(item)
        used += len(text)
    return result, truncated

class ContextBuilder:
    """为某一维度构建 DimContext，自动管理 token 预算。"""

    def __init__(self, repo: "Repository") -> None:
        self._repo = repo

    def build(
        self,
        doc_id: str,
        dimension: str,
        *,
        skills_store: Any = None,
        fts_query_override: str | None = None,
    ) -> DimContext:
        budget = CONTEXT_BUDGETS.get(dimension, _DEFAULT_BUDGET)

        # 1. 拉取维度相关 chunks
        all_chunks = self._repo.get_chunks_by_dimension(doc_id, dimension)
        if not all_chunks:
            # fallback: 取全部 chunks（文档级维度）
            all_chunks = self._repo.get_chunks_by_doc(doc_id)
        chunks, chunk_truncated = _truncate_list_to_budget(all_chunks, budget.chunks * 2)

        # 2. 检索标准条款（用 chunks 里的关键词）
        query = fts_query_override or _build_fts_query(chunks, dimension)
        standards_raw: list[dict[str, Any]] = []
        if query:
            try:
                from src.retrieve.fts_search import search_standards_for_dimension
                standards_raw = search_standards_for_dimension(
                    self._repo, dimension, query, top_k=5
                )
            except Exception as e:
                log.warning("Context FTS 失败 [%s]: %s", dimension, e)
        standards, std_truncated = _truncate_list_to_budget(standards_raw, budget.standards * 2)

        # 3. 检索相关技能（可选）
        skill_docs: list[dict[str, Any]] = []
        if skills_store is not None:
            try:
                skill_docs = skills_store.search(query or dimension, dimension=dimension, top_k=2)
            except Exception:
                pass

        return DimContext(
            dimension=dimension,
            doc_id=doc_id,
            chunks=chunks,
            standards=standards,
            skills=skill_docs,
            budget=budget,
            truncated=chunk_truncated or std_truncated,
        )

def _build_fts_query(chunks: list[dict[str, Any]], dimension: str) -> str:
    """从 chunks 内容里提取有意义的关键词作为 FTS 查询。"""
    _DIM_KEYWORDS: dict[str, list[str]] = {
        "C2_content_completeness": ["职责", "岗位", "操作", "规程", "培训", "应急"],
        "C3_language":             ["语句", "标点", "缩略词", "文字", "语法"],
        "E2_emergency":            ["应急", "处置", "泄漏", "抢险", "疏散"],
        "L2_standards":            ["标准", "GB", "QSY", "TSG", "引用"],
        "C5_logic":                ["压力", "温度", "里程", "时间", "矛盾"],
        "E1_staffing":             ["员工", "工程师", "巡线", "区段", "管道"],
    }
    keywords = _DIM_KEYWORDS.get(dimension, [])
    if keywords:
        return " ".join(keywords[:4])
    # 从前2个chunk标题/内容提取
    texts = [(c.get("title") or "") + " " + (c.get("content") or "")[:200] for c in chunks[:2]]
    return " ".join(texts)[:200]
