"""I5 逃生路线 + 集结点审核。

检查项：
- 疏散方向应向管道两侧（不顺管道方向）
- 集结点在潜在影响半径范围之外
"""

from __future__ import annotations

from typing import Any

from src.agents.base import AgentResult, Finding
from src.agents.scene2.vision_base import VisionAgent


class I5EvacuationAgent(VisionAgent):
    dimension = "I5_evacuation"
    image_types = ("evacuation_route", "assembly_point")

    def analyze(self, images: list[dict[str, Any]]) -> AgentResult:
        findings: list[Finding] = []
        evacuation_count = 0
        assembly_total = 0

        for img in images:
            chunk_id = img.get("chunk_id", "")
            img_type = img.get("image_type", "")
            a = img.get("analysis") or {}

            if img_type == "evacuation_route":
                evacuation_count += 1
                if not a.get("evacuation_arrows_present"):
                    findings.append(Finding(
                        severity="high",
                        description="逃生路线图未标注疏散方向箭头",
                        rule_id="I5.no_arrows", chunk_id=chunk_id,
                    ))
                if a.get("follows_pipeline_direction"):
                    findings.append(Finding(
                        severity="high",
                        description="疏散方向沿管道延伸（应向两侧）",
                        rule_id="I5.wrong_direction", chunk_id=chunk_id,
                    ))
                elif not a.get("evacuates_to_both_sides", True):
                    findings.append(Finding(
                        severity="medium",
                        description="疏散方向未向管道两侧",
                        rule_id="I5.not_both_sides", chunk_id=chunk_id,
                    ))

            elif img_type == "assembly_point":
                cnt = int(a.get("assembly_points_count") or 0)
                assembly_total += cnt
                if cnt == 0:
                    findings.append(Finding(
                        severity="high",
                        description="集结点图未标注任何集结点",
                        rule_id="I5.no_assembly", chunk_id=chunk_id,
                    ))
                if not a.get("outside_impact_radius", True):
                    findings.append(Finding(
                        severity="high",
                        description="集结点位于潜在影响半径范围内",
                        rule_id="I5.assembly_in_radius", chunk_id=chunk_id,
                    ))

        if evacuation_count == 0 and assembly_total == 0:
            return AgentResult(
                dimension=self.dimension,
                verdict="fail", score=2, confidence=80,
                details="未找到逃生路线或集结点要素",
                findings=findings, need_human_review=True,
            )

        if any(f.severity == "high" for f in findings):
            verdict, score, conf = "fail", 5, 80
        elif findings:
            verdict, score, conf = "partial", 9, 75
        else:
            verdict, score, conf = "pass", 12, 90

        return AgentResult(
            dimension=self.dimension,
            verdict=verdict, score=score, confidence=conf,
            findings=findings,
            details=f"逃生图{evacuation_count}张，集结点共{assembly_total}个",
            extra={"evacuation_images": evacuation_count, "assembly_points": assembly_total},
        )
