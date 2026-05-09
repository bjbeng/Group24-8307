"""文档标准引用核查：outdated / unlisted / untraceable。

三种 finding：
  outdated    — 文档引用的标准年份旧于库中最新版
  unlisted    — 正文提到某标准号，但"引用标准"列表中没有
  untraceable — 标准号在库中找不到，无法核验
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from src.standards_lib.normalizer import Citation, extract_citations
from src.store.repository import Repository

log = logging.getLogger(__name__)

# "引用标准"章节常见标题关键词
_REF_SECTION_KEYWORDS = {
    "规范性引用文件", "引用标准", "引用文件",
    "参考标准", "参考文献", "normative references",
}


@dataclass(frozen=True)
class VersionFinding:
    kind: str           # "outdated" | "unlisted" | "untraceable"
    number_raw: str     # 文档中出现的原始字符串
    cited_year: int | None
    latest_year: int | None
    evidence: str       # 上下文片段
    severity: str       # "high" | "medium" | "low"

    def to_finding_dict(self) -> dict[str, Any]:
        if self.kind == "outdated":
            desc = (
                f"引用非最新标准：{self.number_raw}（文档年份 {self.cited_year}，"
                f"库中最新 {self.latest_year}）"
            )
        elif self.kind == "unlisted":
            desc = f"正文引用标准未列入引用清单：{self.number_raw}"
        else:
            desc = f"标准编号无法追溯（库中不存在）：{self.number_raw}"

        return {
            "severity": self.severity,
            "description": desc,
            "evidence": self.evidence[:200],
            "rule_id": f"STDLIB:{self.kind.upper()}",
        }


def _extract_reference_section(chunks: list[dict[str, Any]]) -> set[str]:
    """从文档 chunks 中找"规范性引用文件"章节，返回其中出现的标准号（normalized）。

    进入策略：发现标题含关键词的 heading chunk。
    退出策略：遇到下一个 heading chunk（chunk_type==heading 且标题非空）即停止。
    """
    in_ref = False
    ref_text_parts: list[str] = []

    for c in chunks:
        title = (c.get("title") or "").strip()
        content = c.get("content") or ""
        is_heading = c.get("chunk_type") == "heading" or bool(title)

        if any(kw in title for kw in _REF_SECTION_KEYWORDS):
            in_ref = True
            ref_text_parts.append(content)
            continue

        if in_ref:
            # 遇到新标题 → 引用章节结束
            if is_heading and title:
                break
            ref_text_parts.append(content)

    if not ref_text_parts:
        return set()

    ref_text = "\n".join(ref_text_parts)
    return {c.number_normalized for c in extract_citations(ref_text)}


def _full_doc_text(chunks: list[dict[str, Any]]) -> str:
    return "\n".join(c.get("content") or "" for c in chunks)


def check_standard_versions(
    chunks: list[dict[str, Any]],
    repo: Repository,
) -> list[VersionFinding]:
    """对整个文档执行三种标准引用核查，返回所有 findings。"""
    if not chunks:
        return []

    full_text = _full_doc_text(chunks)
    all_citations = extract_citations(full_text)
    if not all_citations:
        return []

    ref_section_numbers = _extract_reference_section(chunks)
    has_ref_section = bool(ref_section_numbers)

    findings: list[VersionFinding] = []

    for cit in all_citations:
        row = repo.get_standard_version(cit.number_normalized)

        if row is None:
            # untraceable：库中不存在
            findings.append(VersionFinding(
                kind="untraceable",
                number_raw=cit.number_raw,
                cited_year=cit.year,
                latest_year=None,
                evidence=cit.context,
                severity="low",
            ))
            continue

        # outdated：库中有，但状态是 superseded 或年份旧
        latest_year: int | None = row.get("latest_year")
        status = row.get("status", "current")
        if status == "superseded":
            superseded_by = row.get("superseded_by", "")
            findings.append(VersionFinding(
                kind="outdated",
                number_raw=cit.number_raw,
                cited_year=cit.year,
                latest_year=latest_year,
                evidence=f"{cit.context}（已被 {superseded_by} 取代）",
                severity="high",
            ))
        elif cit.year and latest_year and cit.year < latest_year:
            findings.append(VersionFinding(
                kind="outdated",
                number_raw=cit.number_raw,
                cited_year=cit.year,
                latest_year=latest_year,
                evidence=cit.context,
                severity="medium",
            ))

        # unlisted：正文出现但未在引用清单中（仅当文档有引用章节时才判断）
        if has_ref_section and cit.number_normalized not in ref_section_numbers:
            findings.append(VersionFinding(
                kind="unlisted",
                number_raw=cit.number_raw,
                cited_year=cit.year,
                latest_year=latest_year,
                evidence=cit.context,
                severity="medium",
            ))

    return findings


def version_findings_extra(findings: list[VersionFinding]) -> dict[str, Any]:
    """把 findings 汇总为 AgentResult.extra 里的 version_check 字段。"""
    return {
        "version_check": {
            "outdated": [f.number_raw for f in findings if f.kind == "outdated"],
            "unlisted":  [f.number_raw for f in findings if f.kind == "unlisted"],
            "untraceable": [f.number_raw for f in findings if f.kind == "untraceable"],
            "total": len(findings),
        }
    }
