"""I6 水体敏感型围油设施图审核（条件触发）。

仅在 hca_type='water_sensitive' 时运行；其余场景跳过返回 uncertain（不报失败）。
"""

from __future__ import annotations

from typing import Any

from src.agents.base import AgentResult, Finding
from src.agents.scene2.vision_base import VisionAgent


class I6WaterContainmentAgent(VisionAgent):
    dimension = "I6_water_containment"
    image_types = ("water_containment",)

    def __init__(self, provider, vision_model, *, repo=None,
                 hca_type: str | None = None, temperature: float = 0.0):
        super().__init__(provider, vision_model, repo=repo, temperature=temperature)
        self.hca_type = hca_type

    def run(self, image_chunks: list[dict[str, Any]]) -> AgentResult:
        if self.hca_type and self.hca_type != "water_sensitive":
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain", score=0, confidence=80,
                details=f"高后果区类型={self.hca_type}，非水体敏感型，I6 不适用。",
                extra={"skipped": True, "reason": "not_water_sensitive"},
            )
        return super().run(image_chunks)

    def analyze(self, images: list[dict[str, Any]]) -> AgentResult:
        findings: list[Finding] = []
        any_facility_marked = False

        for img in images:
            chunk_id = img.get("chunk_id", "")
            a = img.get("analysis") or {}

            if not a.get("water_body_visible"):
                findings.append(Finding(
                    severity="medium",
                    description="未识别到明确的水体",
                    rule_id="I6.no_water", chunk_id=chunk_id,
                ))
            if a.get("containment_facility_marked"):
                any_facility_marked = True
            else:
                findings.append(Finding(
                    severity="high",
                    description="未标注围油设施",
                    rule_id="I6.no_facility", chunk_id=chunk_id,
                ))
            if not a.get("facility_position_appropriate", True):
                findings.append(Finding(
                    severity="high",
                    description="围油设施位置不合理",
                    rule_id="I6.bad_position", chunk_id=chunk_id,
                ))

        if not any_facility_marked:
            verdict, score, conf = "fail", 3, 75
        elif any(f.severity == "high" for f in findings):
            verdict, score, conf = "fail", 5, 80
        elif findings:
            verdict, score, conf = "partial", 9, 75
        else:
            verdict, score, conf = "pass", 12, 90

        return AgentResult(
            dimension=self.dimension,
            verdict=verdict, score=score, confidence=conf,
            findings=findings,
            details=f"围油设施图 {len(images)} 张",
        )
