"""场景识别路由：根据文档关键词决定场景一/场景二。"""

from __future__ import annotations

from src.chunk.models import Chunk


SCENARIO_1_KEYWORDS = (
    "作业指导书", "岗位职责", "操作规程", "巡回检查",
    "应急处置卡", "岗位条件", "作业指引", "巡线工",
)
SCENARIO_1_STRONG = ("作业指导书", "岗位职责", "操作规程")

SCENARIO_2_KEYWORDS = (
    "高后果区", "管控方案", "一区一案", "潜在影响半径",
    "人员密集型", "环境敏感型", "水体敏感型",
    "应急疏散集结点", "高后果区编号", "高后果区基本信息",
    "高后果区识别", "影响半径", "围油栏",
)
SCENARIO_2_STRONG = ("一区一案", "高后果区基本信息", "应急疏散集结点", "管控方案")

HCA_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "population_intensive": ("人员密集型", "人员密集"),
    "environmental_sensitive": ("环境敏感型", "环境敏感"),
    "water_sensitive": ("水体敏感型", "水体敏感"),
}


def _full_text(chunks: list[Chunk]) -> str:
    parts: list[str] = []
    for c in chunks:
        if c.content:
            parts.append(c.content)
        if c.title:
            parts.append(c.title)
    return "\n".join(parts)


def _count_hits(text: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for kw in keywords if kw in text)


def detect_scenario(chunks: list[Chunk]) -> str:
    text = _full_text(chunks)
    if not text.strip():
        return "unknown"

    s1 = _count_hits(text, SCENARIO_1_KEYWORDS)
    s2 = _count_hits(text, SCENARIO_2_KEYWORDS)
    s1_strong = _count_hits(text, SCENARIO_1_STRONG)
    s2_strong = _count_hits(text, SCENARIO_2_STRONG)

    if s1_strong >= 2 and s1_strong >= s2_strong:
        return "scenario_1"
    if s2_strong >= 2 and s2_strong > s1_strong:
        return "scenario_2"

    if s2 >= 4 and s2 >= max(3, int(s1 * 1.5)):
        return "scenario_2"
    if s1 >= 2 and s1 >= s2:
        return "scenario_1"
    if s2 > s1 and s2 >= 2:
        return "scenario_2"
    if s1 > 0:
        return "scenario_1"
    return "unknown"


def detect_hca_type(chunks: list[Chunk]) -> str | None:
    text = _full_text(chunks)
    if not text.strip():
        return None
    scores: dict[str, int] = {}
    for type_id, keywords in HCA_TYPE_KEYWORDS.items():
        score = _count_hits(text, keywords)
        if score > 0:
            scores[type_id] = score
    if not scores:
        return None
    return sorted(scores.items(), key=lambda kv: -kv[1])[0][0]
