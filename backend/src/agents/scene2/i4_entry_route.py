"""I4 入场线路图标注审核。

检查项：路线不能穿山/穿墙/无桥跨河/穿建筑物/不在可行车道。
"""

from __future__ import annotations

from typing import Any

from src.agents.base import AgentResult, Finding
from src.agents.scene2.vision_base import VisionAgent


FORBIDDEN_OBSTACLES = ("山地", "山", "墙", "建筑物", "河流")


class I4EntryRouteAgent(VisionAgent):
    dimension = "I4_entry_route"
    image_types = ("entry_route",)

    def analyze(self, images: list[dict[str, Any]]) -> AgentResult:
        findings: list[Finding] = []
        any_route_marked = False

        for img in images:
            chunk_id = img.get("chunk_id", "")
            a = img.get("analysis") or {}

            if a.get("route_marked"):
                any_route_marked = True
            else:
                findings.append(Finding(
                    severity="high",
                    description="入场线路图未标注具体路线",
                    rule_id="I4.no_route", chunk_id=chunk_id,
                ))

            obstacles = a.get("crosses_obstacles") or []
            for ob in obstacles:
                if any(f in str(ob) for f in FORBIDDEN_OBSTACLES):
                    findings.append(Finding(
                        severity="high",
                        description=f"入场线路穿越禁区：{ob}",
                        rule_id="I4.forbidden_obstacle", chunk_id=chunk_id,
                    ))

            if not a.get("vehicle_accessible", True):
                findings.append(Finding(
                    severity="medium",
                    description="入场线路不在可行车道路上",
                    rule_id="I4.no_vehicle", chunk_id=chunk_id,
                ))

            if not a.get("text_description_present", True):
                findings.append(Finding(
                    severity="low",
                    description="缺少文字说明",
                    rule_id="I4.no_text", chunk_id=chunk_id,
                ))

        if not any_route_marked:
            verdict, score, conf = "fail", 3, 80
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
            details=f"入场线路图 {len(images)} 张",
        )
