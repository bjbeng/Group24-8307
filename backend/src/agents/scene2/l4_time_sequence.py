"""L4 时间逻辑一致 —— 编制时间 ≥ 风险评价时间 ≥ 识别时间，且年份一致。"""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Any

from src.agents.base import AgentResult, BaseAgent, Finding


log = logging.getLogger(__name__)

_DIM = "L4_time_sequence"

# 通用日期：YYYY-M-D / YYYY/M/D / YYYY年M月D日 / YYYY年M月
DATE_PATTERN = re.compile(
    r"(\d{4})\s*[-./年]\s*(\d{1,2})\s*[-./月]\s*(\d{1,2})?\s*日?"
)

# 三类时间锚点关键词
TIME_ANCHORS: dict[str, tuple[str, ...]] = {
    "compile": ("编制时间", "编制日期", "封面编制", "封面日期", "方案编制"),
    "evaluate": ("风险评价时间", "风险评价日期", "评价时间", "评价日期",
                 "风险评估时间", "风险评估日期"),
    "identify": ("识别时间", "识别日期", "高后果区识别", "辨识时间", "辨识日期"),
}


def _scan_date_near(text: str, keywords: tuple[str, ...], window: int = 50) -> dt.date | None:
    """在 text 中查找 keyword 后 window 字符内的第一个日期。"""
    for kw in keywords:
        idx = text.find(kw)
        if idx < 0:
            continue
        snippet = text[idx: idx + len(kw) + window]
        m = DATE_PATTERN.search(snippet)
        if not m:
            continue
        y, mo = int(m.group(1)), int(m.group(2))
        d = int(m.group(3)) if m.group(3) else 1
        try:
            return dt.date(y, mo, d)
        except ValueError:
            continue
    return None


class L4TimeSequenceAgent(BaseAgent):
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

        compile_dt = _scan_date_near(full_text, TIME_ANCHORS["compile"])
        evaluate_dt = _scan_date_near(full_text, TIME_ANCHORS["evaluate"])
        identify_dt = _scan_date_near(full_text, TIME_ANCHORS["identify"])

        present = {k: v for k, v in zip(
            ("compile", "evaluate", "identify"),
            (compile_dt, evaluate_dt, identify_dt),
        ) if v is not None}

        if len(present) < 2:
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain", score=0, confidence=25,
                details=(
                    f"未抽取到足够的时间点（编制/评价/识别），"
                    f"实际抽到：{list(present.keys())}"
                ),
                need_human_review=True,
                extra={"compile": str(compile_dt), "evaluate": str(evaluate_dt),
                       "identify": str(identify_dt)},
            )

        findings: list[Finding] = []

        # 1. 时序：编制 ≥ 评价 ≥ 识别
        if compile_dt and evaluate_dt and compile_dt < evaluate_dt:
            findings.append(Finding(
                severity="high",
                description=f"编制时间({compile_dt})早于风险评价时间({evaluate_dt})",
                rule_id="L4.compile_before_evaluate",
            ))
        if evaluate_dt and identify_dt and evaluate_dt < identify_dt:
            findings.append(Finding(
                severity="high",
                description=f"风险评价时间({evaluate_dt})早于识别时间({identify_dt})",
                rule_id="L4.evaluate_before_identify",
            ))
        if compile_dt and identify_dt and compile_dt < identify_dt:
            findings.append(Finding(
                severity="high",
                description=f"编制时间({compile_dt})早于识别时间({identify_dt})",
                rule_id="L4.compile_before_identify",
            ))

        # 2. 年份一致
        years = {d.year for d in present.values()}
        if len(years) > 1:
            findings.append(Finding(
                severity="medium",
                description=f"三类时间年份不一致：{sorted(years)}",
                rule_id="L4.year_mismatch",
            ))

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
                f"编制={compile_dt}, 评价={evaluate_dt}, 识别={identify_dt}"
            ),
            extra={
                "compile": str(compile_dt) if compile_dt else None,
                "evaluate": str(evaluate_dt) if evaluate_dt else None,
                "identify": str(identify_dt) if identify_dt else None,
            },
        )
