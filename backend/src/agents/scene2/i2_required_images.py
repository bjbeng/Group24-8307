"""I2 必备图完整性 —— 纯规则维度。

按高后果区类型校验图片清单：
- 人员密集型：影像图 + 现场图 + 入场线路 + 逃生路线 + 集合点 + 应急物资点
- 环境敏感型：影像图 + 现场图 + 入场线路 + 应急物资点
- 水体敏感型：在环境敏感型基础上增加 围油设施图
"""

from __future__ import annotations

import logging
from typing import Any

from src.agents.base import AgentResult, BaseAgent, Finding


log = logging.getLogger(__name__)


def _conditional_required_from_text(full_text: str) -> tuple[set[str], list[str]]:
    """赛题补充：正文出现特定表述时，额外要求一类图。"""
    extra: set[str] = set()
    reasons: list[str] = []

    pop_dense = ("人员密集型" in full_text) or ("人员密集" in full_text)
    if pop_dense and "附表" in full_text:
        extra.add("municipal_crossing")
        reasons.append(
            "出现「人员密集型高后果区」类表述且含「附表」→需市政管网交叉位置图"
        )

    if (
        ("输油管道" in full_text or "输油管线" in full_text)
        and "环境敏感" in full_text
        and "高后果区" in full_text
    ):
        extra.add("water_containment")
        reasons.append(
            "出现「输油管道环境敏感类高后果区」类描述→需水体敏感围油设施示意图"
        )

    return extra, reasons


def _chunks_full_text(chunk_rows: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for c in chunk_rows:
        t = (c.get("title") or "").strip()
        b = (c.get("content") or "").strip()
        if t:
            parts.append(t)
        if b:
            parts.append(b)
    return "\n".join(parts)


# 各类型必需的 image_type 集合
REQUIRED_BY_HCA_TYPE: dict[str, set[str]] = {
    "population_intensive": {
        "hca_aerial", "site_photo", "entry_route",
        "evacuation_route", "assembly_point", "emergency_assets",
    },
    "environmental_sensitive": {
        "hca_aerial", "site_photo", "entry_route", "emergency_assets",
    },
    "water_sensitive": {
        "hca_aerial", "site_photo", "entry_route",
        "emergency_assets", "water_containment",
    },
}

# 中文名称映射（findings 用）
TYPE_CN: dict[str, str] = {
    "hca_aerial": "高后果区影像图",
    "site_photo": "高后果区现场图",
    "entry_route": "入场线路图",
    "evacuation_route": "逃生路线图",
    "assembly_point": "应急疏散集结点图",
    "emergency_assets": "应急物资存放点图",
    "water_containment": "水体敏感型围油设施图",
    "municipal_crossing": "市政管网交叉图",
}


class I2RequiredImagesAgent(BaseAgent):
    dimension = "I2_required_images"

    def __init__(self, provider=None, text_model="", **kwargs) -> None:
        super().__init__(provider, text_model, temperature=0.0)

    def run(
        self,
        chunks: list[dict[str, Any]],
        image_chunks: list[dict[str, Any]] | None = None,
    ) -> AgentResult:
        if image_chunks is None:
            image_chunks = []

        # 重建 Chunk-like 列表用于 detect_hca_type（延迟 import 避免环依）
        from src.chunk.models import Chunk, ChunkType
        from src.pipeline.scenario_router import detect_hca_type
        chunk_objs = []
        for c in chunks:
            try:
                chunk_objs.append(Chunk(
                    chunk_id=c.get("chunk_id", ""),
                    doc_id=c.get("doc_id", ""),
                    chunk_type=ChunkType(c.get("chunk_type", "text")),
                    section_path=c.get("section_path", "") or "",
                    title=c.get("title", "") or "",
                    content=c.get("content", "") or "",
                    paragraph_index=c.get("paragraph_index", 0) or 0,
                    anchor_text=c.get("anchor_text", "") or "",
                ))
            except Exception:
                continue

        hca_type = detect_hca_type(chunk_objs)
        if hca_type is None:
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                score=0, confidence=20,
                details="未识别到高后果区类型（人员密集/环境敏感/水体敏感），跳过必备图校验。",
                need_human_review=True,
                extra={"hca_type": None},
            )

        full_text = _chunks_full_text(chunks)
        cond_types, cond_reasons = _conditional_required_from_text(full_text)

        required = set(REQUIRED_BY_HCA_TYPE.get(hca_type, set()))
        required |= cond_types
        present_types = {img.get("image_type", "") for img in image_chunks}

        missing = required - present_types
        findings: list[Finding] = []
        for t in sorted(missing):
            findings.append(Finding(
                severity="high",
                description=f"缺少必备图：{TYPE_CN.get(t, t)}",
                evidence=f"hca_type={hca_type}, 已有 image_types={sorted(present_types)}",
                rule_id=f"I2.missing_{t}",
            ))

        if not missing:
            verdict, score, conf = "pass", 12, 90
        elif len(missing) <= len(required) // 2:
            verdict, score, conf = "partial", 8, 80
        else:
            verdict, score, conf = "fail", 4, 80

        return AgentResult(
            dimension=self.dimension,
            verdict=verdict, score=score, confidence=conf,
            findings=findings,
            details=(
                f"高后果区类型={hca_type}，必备图 {len(required)} 类，"
                f"缺失 {len(missing)} 类。"
            ),
            extra={
                "hca_type": hca_type,
                "required_types": sorted(required),
                "present_types": sorted(present_types),
                "missing_types": sorted(missing),
                "conditional_required": sorted(cond_types),
                "conditional_required_reasons": cond_reasons,
            },
        )
