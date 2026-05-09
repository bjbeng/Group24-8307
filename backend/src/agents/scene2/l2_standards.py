"""场景二 L2 标准遵从度 —— 是否参照 GB32167（高后果区识别标准）。"""
from __future__ import annotations

import re
from typing import Any

from src.agents.base import AgentResult, BaseAgent, Finding

_DIM = "L2_standards"

_REQUIRED_STANDARDS = [
    "GB32167",
    "GB/T 32167",
    "GB 32167",
]

_RELATED_STANDARDS = [
    "GB50251", "GB50253", "SY/T 6621", "SY/T 6648",
    "AQ 2012", "AQ2012",
]


class L2StandardsAgent(BaseAgent):
    dimension = _DIM

    def run(self, chunks: list[dict[str, Any]]) -> AgentResult:
        full_text = "\n".join(
            (c.get("content") or "") for c in chunks if c.get("content")
        )
        if not full_text.strip():
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain", score=0, confidence=15,
                details="无文本可审。", need_human_review=True,
            )

        findings: list[Finding] = []

        # 必须引用 GB32167
        gb_present = any(s in full_text for s in _REQUIRED_STANDARDS)
        if not gb_present:
            findings.append(Finding(
                severity="high",
                description="未引用或提及 GB32167（油气输送管道高后果区识别与分级管理）",
                rule_id="L2.missing_gb32167",
            ))

        # 相关标准命中数（加分项，不扣分）
        related_hits = [s for s in _RELATED_STANDARDS if s in full_text]

        if findings:
            verdict, score, conf = "fail", 4, 85
        else:
            verdict, score, conf = "pass", 12, 90

        return AgentResult(
            dimension=self.dimension,
            verdict=verdict, score=score, confidence=conf,
            findings=findings,
            details=(
                f"GB32167={'已引用' if gb_present else '未引用'}；"
                f"相关标准命中：{related_hits or '无'}"
            ),
            extra={"gb32167_present": gb_present, "related_hits": related_hits},
        )
