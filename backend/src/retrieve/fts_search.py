"""FTS5 关键词检索包装。

实现路径 1（评审决定）：不上向量库；中文用 jieba 分词后入 FTS 索引/查询。
"""

from __future__ import annotations

from typing import Any

import jieba

from src.store.repository import Repository


# 维度 → 标准白名单（与 config/dimensions.yaml 的 DIMENSION_STANDARDS 对齐）
_DEFAULT_DIMENSION_STANDARDS: dict[str, list[str]] = {
    "C1_structure": ["QSY1217", "GBT1.1", "GBT19023", "GBT25000.51"],
    "C2_content_completeness": [
        "TSG31", "GBT21246", "QSY1217",
        "GB50251", "GB50253",           # 管道设计规范 — 技术参数基准
        "GBT21447", "GBT21448",         # 腐蚀防护 — 技术参数
        "SYT5922",                       # 运行规范 — 操作规程/岗位职责
        "SYT6069",                       # 自动化运行 — 技术参数
    ],
    "C3_language": ["GBT1.1", "GBT19023"],
    "C4_reference": ["GBT1.1", "QSY1217"],
    "C5_logic": ["QSY1217", "GB50251", "GB50253", "SYT5922"],
    "E1_staffing": ["QSY1217", "SYT5922"],
    "E2_emergency": ["QSY1217", "AQ3057", "SYT5922"],
    "L2_standards": ["GB32167", "GB50251", "GB50253", "SYT6069", "GBT21447", "GBT21448"],
}


def tokenize_for_fts(text: str) -> str:
    """jieba 分词 + 去停用词；返回空格分隔串供 FTS5 MATCH 使用。"""
    tokens = [t.strip() for t in jieba.lcut(text) if t.strip() and len(t.strip()) > 1]
    # OR 拼接：FTS5 默认是 OR；显式写也兼容
    return " OR ".join(tokens) if tokens else text


def search_standards_for_dimension(
    repo: Repository,
    dimension: str,
    query: str,
    top_k: int = 3,
    dimension_standards: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """根据维度白名单检索标准条款。

    流程：
    1. 查表获取该维度允许的 standard_name 白名单
    2. jieba 切词
    3. FTS5 MATCH，限白名单过滤，取 top_k
    """
    mapping = dimension_standards or _DEFAULT_DIMENSION_STANDARDS
    standards = mapping.get(dimension, [])
    fts_query = tokenize_for_fts(query)
    return repo.search_standards(
        query=fts_query,
        standard_filter=standards or None,
        top_k=top_k,
    )
