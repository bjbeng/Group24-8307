"""I7 市政管网交叉图审核（条件触发）。

仅在 hca_type='population_intensive' 时强制要求；其他类型若有此图也会评估。
"""

from __future__ import annotations

from typing import Any

from src.agents.base import AgentResult, Finding
from src.agents.scene2.vision_base import VisionAgent


class I7MunicipalCrossingAgent(VisionAgent):
    dimension = "I7_municipal_crossing"
    image_types = ("municipal_crossing",)

    def __init__(self, provider, vision_model, *, repo=None,
                 hca_type: str | None = None, temperature: float = 0.0):
        super().__init__(provider, vision_model, repo=repo, temperature=temperature)
        self.hca_type = hca_type

    def run(self, image_chunks: list[dict[str, Any]]) -> AgentResult:
        relevant = [img for img in image_chunks
                    if img.get("image_type") in self.image_types]
        if not relevant:
            # 仅人员密集型必备；其他类型缺失视为 uncertain
            severity_msg = "人员密集型/城区管道必备，但未找到该图。" \
                if self.hca_type == "population_intensive" \
                else "未找到市政交叉图（非人员密集型，可能不适用）。"
            verdict = "fail" if self.hca_type == "population_intensive" else "uncertain"
            return AgentResult(
                dimension=self.dimension,
                verdict=verdict,
                score=0 if verdict == "fail" else 0,
                confidence=80,
                details=severity_msg,
                need_human_review=True,
            )
        return self.analyze(relevant)

    def analyze(self, images: list[dict[str, Any]]) -> AgentResult:
        findings: list[Finding] = []
        total_crossings = 0

        for img in images:
            chunk_id = img.get("chunk_id", "")
            a = img.get("analysis") or {}

            if not a.get("crossing_marked"):
                findings.append(Finding(
                    severity="high",
                    description="市政交叉位置未标注",
                    rule_id="I7.no_crossing", chunk_id=chunk_id,
                ))
            cnt = int(a.get("crossing_count") or 0)
            total_crossings += cnt
            if not a.get("text_description_present", True):
                findings.append(Finding(
                    severity="medium",
                    description="缺少文字说明",
                    rule_id="I7.no_text", chunk_id=chunk_id,
                ))
            if not a.get("depth_marked", False):
                findings.append(Finding(
                    severity="low",
                    description="未标注交叉点埋深",
                    rule_id="I7.no_depth", chunk_id=chunk_id,
                ))

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
            details=f"市政交叉图 {len(images)} 张，交叉点共 {total_crossings} 个",
            extra={"crossings_total": total_crossings},
        )
