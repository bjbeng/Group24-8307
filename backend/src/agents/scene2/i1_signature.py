"""I1 签字页手签识别。

输入：image_chunks 中 image_type='approval' 的图（已由 image_pipeline 预填 analysis）
检查：
- 编制/校对/审核/批准 角色齐全
- 日期格式合法
- 时序：编制日期 ≤ 审核日期 ≤ 批准日期
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from src.agents.base import AgentResult, Finding
from src.agents.scene2.vision_base import VisionAgent


log = logging.getLogger(__name__)

REQUIRED_ROLES = ("编制", "校对", "审核", "批准")


def _parse_date(s: str) -> dt.date | None:
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日", "%Y.%m.%d"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


class I1SignatureAgent(VisionAgent):
    dimension = "I1_signature"
    image_types = ("approval",)

    def analyze(self, images: list[dict[str, Any]]) -> AgentResult:
        findings: list[Finding] = []
        all_signatures: list[dict] = []
        date_seq_ok = True
        all_required_signed = True

        for img in images:
            analysis = img.get("analysis") or {}
            sigs = analysis.get("signatures") or []
            chunk_id = img.get("chunk_id", "")

            if not sigs:
                findings.append(Finding(
                    severity="high",
                    description="签字页未识别到任何签名",
                    evidence=img.get("description", "")[:200],
                    rule_id="I1.no_signature",
                    chunk_id=chunk_id,
                ))
                all_required_signed = False
                continue

            all_signatures.extend(sigs)

            # 检查必备角色
            roles_present = {str(s.get("role", "")) for s in sigs
                             if s.get("name_present")}
            for role in REQUIRED_ROLES:
                if role not in roles_present and role != "校对":  # 校对非强制
                    findings.append(Finding(
                        severity="medium",
                        description=f"缺少{role}签字",
                        evidence=f"已有：{','.join(sorted(roles_present))}",
                        rule_id="I1.missing_role",
                        chunk_id=chunk_id,
                    ))
                    all_required_signed = False

            # 检查日期时序：编制 ≤ 审核 ≤ 批准
            dates: dict[str, dt.date] = {}
            for s in sigs:
                role = str(s.get("role", ""))
                d = _parse_date(str(s.get("date") or ""))
                if d:
                    dates[role] = d

            seq_pairs = [("编制", "审核"), ("审核", "批准"), ("编制", "批准")]
            for early, late in seq_pairs:
                if early in dates and late in dates and dates[early] > dates[late]:
                    date_seq_ok = False
                    findings.append(Finding(
                        severity="high",
                        description=f"{early}日期({dates[early]})晚于{late}日期({dates[late]})",
                        evidence=f"违反时序：{early} ≤ {late}",
                        rule_id="I1.date_sequence",
                        chunk_id=chunk_id,
                    ))

        # 判定 verdict
        if not all_signatures:
            return AgentResult(
                dimension=self.dimension,
                verdict="fail", score=0, confidence=80,
                details="审批页未识别到签名",
                findings=findings,
                need_human_review=True,
            )

        has_high = any(f.severity == "high" for f in findings)
        if has_high:
            verdict, score, conf = "fail", 5, 80
        elif findings:
            verdict, score, conf = "partial", 8, 75
        else:
            verdict, score, conf = "pass", 12, 90

        return AgentResult(
            dimension=self.dimension,
            verdict=verdict, score=score, confidence=conf,
            findings=findings,
            details=f"识别 {len(all_signatures)} 个签名；时序{'通过' if date_seq_ok else '违反'}",
            extra={
                "signatures_total": len(all_signatures),
                "all_required_signed": all_required_signed,
                "date_sequence_valid": date_seq_ok,
            },
        )
