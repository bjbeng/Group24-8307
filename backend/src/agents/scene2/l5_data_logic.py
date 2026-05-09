"""L5 数据逻辑正确性。

校验：
- 电位测试结果 ∈ [-1.2V, -0.85V]
- 风险等级 ∈ {低, 中, 较高, 高}
- 风险评价中可能性、后果值、风险值为数值
"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.agents.base import AgentResult, BaseAgent, Finding


log = logging.getLogger(__name__)

_DIM = "L5_data_logic"

# 电位（含负号）："电位 -0.95 V" 或 "管地电位 -1.05V"
RE_POTENTIAL = re.compile(r"电位[^-\d]{0,8}(-?\d+(?:\.\d+)?)\s*V", re.IGNORECASE)

# 风险等级：常见出现 "风险等级：较高" / "风险等级 高"
RE_RISK_LEVEL = re.compile(r"风险等级[：:\s]*([低中高])(高|较高)?")

VALID_RISK_LEVELS = {"低", "中", "较高", "高"}

# 风险评价数据：可能性 / 后果值 / 风险值 后面跟数字
RE_RISK_NUM = re.compile(r"(可能性|后果值|风险值)[：:\s]*([\d.]+)")


class L5DataLogicAgent(BaseAgent):
    dimension = _DIM

    def __init__(self, provider=None, text_model="", *, repo=None,
                 temperature: float = 0.0):
        super().__init__(provider, text_model, temperature=temperature)
        self.repo = repo

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

        # 1. 电位
        potentials = [float(v) for v in RE_POTENTIAL.findall(full_text)]
        out_of_range = [p for p in potentials if not (-1.2 <= p <= -0.85)]
        for p in out_of_range:
            findings.append(Finding(
                severity="high",
                description=f"电位测试值 {p}V 超出标准范围 [-1.2V, -0.85V]",
                rule_id="L5.potential_out_of_range",
            ))

        # 2. 风险等级
        levels_found: list[str] = []
        for m in RE_RISK_LEVEL.finditer(full_text):
            lvl = m.group(0).split("等级")[-1].lstrip("：: ").strip()
            # 取 "较高"、"高"、"中"、"低"
            for valid in ("较高", "高", "中", "低"):
                if lvl.startswith(valid):
                    levels_found.append(valid)
                    break

        invalid_levels = [lv for lv in levels_found if lv not in VALID_RISK_LEVELS]
        if invalid_levels:
            findings.append(Finding(
                severity="medium",
                description=f"风险等级取值非法：{invalid_levels}",
                rule_id="L5.invalid_risk_level",
            ))

        # 3. 风险评价数据是否数值
        risk_data: dict[str, list[str]] = {"可能性": [], "后果值": [], "风险值": []}
        for k, v in RE_RISK_NUM.findall(full_text):
            risk_data[k].append(v)
        non_numeric: list[str] = []
        for k, vals in risk_data.items():
            for v in vals:
                try:
                    float(v)
                except ValueError:
                    non_numeric.append(f"{k}={v}")
        if non_numeric:
            findings.append(Finding(
                severity="medium",
                description=f"风险评价数据非数值：{non_numeric}",
                rule_id="L5.risk_value_not_numeric",
            ))

        # 检测到的数据少则降级 uncertain
        signals = len(potentials) + len(levels_found) + sum(len(v) for v in risk_data.values())
        if signals == 0:
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain", score=0, confidence=25,
                details="未在文档中找到电位/风险等级/风险数据，无法判断。",
                need_human_review=True,
                extra={"signals": 0},
            )

        if any(f.severity == "high" for f in findings):
            verdict, score, conf = "fail", 4, 85
        elif findings:
            verdict, score, conf = "partial", 8, 80
        else:
            verdict, score, conf = "pass", 12, 90

        return AgentResult(
            dimension=self.dimension,
            verdict=verdict, score=score, confidence=conf,
            findings=findings,
            details=(
                f"电位 {len(potentials)}个(超范围{len(out_of_range)}); "
                f"风险等级 {len(levels_found)}个; "
                f"风险数据 {sum(len(v) for v in risk_data.values())}条"
            ),
            extra={
                "potentials": potentials,
                "potentials_out_of_range": out_of_range,
                "risk_levels": levels_found,
                "risk_data": risk_data,
            },
        )
