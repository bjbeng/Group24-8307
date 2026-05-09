"""I3 高后果区影像图标注审核。

检查项：
- 管道实线
- 影响半径虚线
- 三条平行线（管道中心线 + 左右影响范围）
- 周边建筑标注（含人数/名称）
"""

from __future__ import annotations

from typing import Any

from src.agents.base import AgentResult, Finding
from src.agents.scene2.vision_base import VisionAgent


class I3AerialAgent(VisionAgent):
    dimension = "I3_aerial"
    image_types = ("hca_aerial",)

    def analyze(self, images: list[dict[str, Any]]) -> AgentResult:
        findings: list[Finding] = []
        any_pipeline_visible = False
        building_count = 0

        for img in images:
            chunk_id = img.get("chunk_id", "")
            a = img.get("analysis") or {}

            if a.get("pipeline_visible"):
                any_pipeline_visible = True
            else:
                findings.append(Finding(
                    severity="high",
                    description="影像图中未明确标注管道",
                    evidence=img.get("description", "")[:200],
                    rule_id="I3.no_pipeline",
                    chunk_id=chunk_id,
                ))

            if not a.get("pipeline_solid_line", False):
                findings.append(Finding(
                    severity="medium",
                    description="管道未用实线标注",
                    rule_id="I3.no_solid_line", chunk_id=chunk_id,
                ))
            if not a.get("impact_radius_dashed", False):
                findings.append(Finding(
                    severity="medium",
                    description="潜在影响半径未用虚线标注",
                    rule_id="I3.no_dashed_radius", chunk_id=chunk_id,
                ))
            if not a.get("three_parallel_lines", False):
                findings.append(Finding(
                    severity="low",
                    description="未识别到三条平行线（管道中心线+左右影响范围）",
                    rule_id="I3.no_three_lines", chunk_id=chunk_id,
                ))

            buildings = a.get("buildings") or []
            building_count += len(buildings)
            if not buildings:
                findings.append(Finding(
                    severity="medium",
                    description="未识别到周边建筑物标注",
                    rule_id="I3.no_buildings", chunk_id=chunk_id,
                ))
            else:
                for b in buildings:
                    if not b.get("distance_marked"):
                        findings.append(Finding(
                            severity="low",
                            description=f"建筑[{b.get('label', '?')}]缺少距离标注",
                            rule_id="I3.building_no_distance", chunk_id=chunk_id,
                        ))

        if not any_pipeline_visible:
            verdict, score, conf = "fail", 4, 75
        elif any(f.severity == "high" for f in findings):
            verdict, score, conf = "fail", 5, 80
        elif sum(1 for f in findings if f.severity == "medium") >= 2:
            verdict, score, conf = "partial", 8, 75
        elif findings:
            verdict, score, conf = "partial", 10, 80
        else:
            verdict, score, conf = "pass", 12, 90

        return AgentResult(
            dimension=self.dimension,
            verdict=verdict, score=score, confidence=conf,
            findings=findings,
            details=f"影像图 {len(images)} 张；建筑物总数 {building_count}",
            extra={"image_count": len(images), "building_count": building_count},
        )
