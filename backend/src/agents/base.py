"""Agent 基础设施：结果模型、JSON 提取、Provider 注入。"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from src.llm import LLMProvider


log = logging.getLogger(__name__)


@dataclass
class FindingLocation:
    """Finding 在文档中的精确定位信息。"""
    chunk_id: str
    section_path: str       # 章节路径，如 "2.1"
    anchor_text: str        # 锚文本（前30字符）
    paragraph_index: int    # 段落索引
    page_number: int | None # 页码（1-based，DOCX 可能没有）
    highlight_text: str     # 高亮文本（anchor_text 或 evidence 片段）
    severity: str           # high/medium/low
    dimension: str           # 维度名


@dataclass
class Finding:
    severity: str           # "high" | "medium" | "low"
    description: str
    evidence: str = ""
    rule_id: str | None = None
    chunk_id: str | None = None
    section_path: str = ""      # 层级路径，如 "3.2.1" 或 "APP_A"
    paragraph_index: int = -1   # 在文档 XML 流中的顺序，用于精确定位批注
    anchor_text: str = ""       # 段落开头片段，供人工核查
    category: str = ""          # 审核分类："content" | "deep" | "template"，空则由输出层推断

    # 赛题格式新增字段
    is_problem: bool = True              # 显式标识是否有问题
    problem_type: str = ""               # 问题类型（如"缺少核心模块"、"附录不完整"）
    rule_basis: str = ""                 # 规则依据（规则原文）
    correction_suggestion: str = ""      # 修改建议

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "severity": self.severity,
            "description": self.description,
            "evidence": self.evidence,
            "rule_id": self.rule_id,
            "chunk_id": self.chunk_id,
        }
        if self.section_path:
            d["section_path"] = self.section_path
        if self.paragraph_index >= 0:
            d["paragraph_index"] = self.paragraph_index
        if self.anchor_text:
            d["anchor_text"] = self.anchor_text
        if self.category:
            d["category"] = self.category
        # 赛题格式字段
        d["is_problem"] = self.is_problem
        if self.problem_type:
            d["problem_type"] = self.problem_type
        if self.rule_basis:
            d["rule_basis"] = self.rule_basis
        if self.correction_suggestion:
            d["correction_suggestion"] = self.correction_suggestion
        return d

    def to_location_dict(self, dimension: str = "") -> dict[str, Any]:
        """返回定位字段，用于前端跳转和高亮。"""
        page_number: int | None = None
        if self.paragraph_index >= 0:
            # paragraph_index 是 0-based，转换为 1-based
            page_number = self.paragraph_index + 1

        highlight = self.anchor_text[:30] if self.anchor_text else (self.evidence[:30] if self.evidence else "")

        return {
            "chunk_id": self.chunk_id or "",
            "section_path": self.section_path,
            "anchor_text": (self.anchor_text[:30] if self.anchor_text else ""),
            "paragraph_index": self.paragraph_index,
            "page_number": page_number,
            "highlight_text": highlight,
            "severity": self.severity,
            "dimension": dimension,
        }

    def to_evidence_dict(self) -> dict[str, Any]:
        """只返回定位字段，用于打标 JSON 的 evidence 块。"""
        return {
            "chunk_id": self.chunk_id or "",
            "section_path": self.section_path,
            "paragraph_index": self.paragraph_index,
            "anchor_text": self.anchor_text,
            "raw_evidence": self.evidence,
        }


@dataclass
class AgentResult:
    """单维度审核结果。

    与 sample_label_result.json 字段对齐：
    - verdict: pass / partial / fail / uncertain
    - score: 维度分数（int）
    - confidence: 置信度 0-100
    - findings: 问题清单
    - extra: 维度专属结构化字段（如 staffing_analysis）
    """

    dimension: str
    verdict: str = "uncertain"
    score: int | None = None
    confidence: int = 0
    findings: list[Finding] = field(default_factory=list)
    details: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    need_human_review: bool = False

    # 赛题格式映射字段
    audit_dimension: str = ""   # 映射后的赛题维度（structure/content/language/logic/compliance）
    audit_subtype: str = ""     # 子类型（如 C1.required_modules）

    def to_dict(self) -> dict[str, Any]:
        d = {
            "dimension": self.dimension,
            "verdict": self.verdict,
            "score": self.score,
            "confidence": self.confidence,
            "findings": [f.to_dict() for f in self.findings],
            "details": self.details,
            "extra": self.extra,
            "need_human_review": self.need_human_review,
        }
        if self.audit_dimension:
            d["audit_dimension"] = self.audit_dimension
        if self.audit_subtype:
            d["audit_subtype"] = self.audit_subtype
        return d

    def to_dict_with_location(self) -> dict[str, Any]:
        """带定位信息的 dict（给前端 Finding 跳转和高亮用）。"""
        d = self.to_dict()
        d["findings"] = [
            f.to_location_dict(self.dimension) for f in self.findings
        ]
        return d

    def to_label_dict(self, rule_ids: list[str] | None = None) -> dict[str, Any]:
        """按 rule_id 分组输出打标 JSON。

        每个检查项独立字段，包含：
        - verdict: pass / partial / fail
        - findings: [{severity, description, evidence:{...}}]

        rule_ids 传入时保证所有检查项都出现（即使没有 finding）。
        """
        # 按 rule_id 分组
        grouped: dict[str, list[Finding]] = {}
        for rule_id in (rule_ids or []):
            grouped[rule_id] = []
        for f in self.findings:
            key = f.rule_id or "unknown"
            grouped.setdefault(key, []).append(f)

        def _verdict(fs: list[Finding]) -> str:
            if not fs:
                return "pass"
            if any(f.severity == "high" for f in fs):
                return "fail"
            return "partial"

        standards: dict[str, Any] = {}
        for rule_id, fs in grouped.items():
            standards[rule_id] = {
                "verdict": _verdict(fs),
                "findings": [
                    {
                        "severity": f.severity,
                        "description": f.description,
                        "evidence": f.to_evidence_dict(),
                    }
                    for f in fs
                ],
            }

        return {
            "dimension": self.dimension,
            "verdict": self.verdict,
            "score": self.score,
            "confidence": self.confidence,
            "details": self.details,
            "standards": standards,
            "need_human_review": self.need_human_review,
        }


@dataclass
class AuditOpinion:
    """单条检查项的人工可读审核意见（Audit 专有）。"""
    check_item: str          # "C1.required_modules"
    verdict: str             # pass / partial / fail
    severity: str            # high / medium / low
    opinion: str             # 核心意见（含"通过了什么"或"缺少什么/有什么问题"）
    evidence_summary: str    # 证据摘要
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_item": self.check_item,
            "verdict": self.verdict,
            "severity": self.severity,
            "opinion": self.opinion,
            "evidence_summary": self.evidence_summary,
            "suggestions": self.suggestions,
        }


@dataclass
class AuditReport:
    """完整人工可读审核报告（Audit 专有）。"""
    doc_id: str
    doc_name: str
    overall_opinion: str     # 总体审核意见（1-2句话）
    overall_verdict: str
    overall_score: int
    per_dimension: dict[str, list[AuditOpinion]] = field(default_factory=dict)
    critical_issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    need_human_review: bool = False
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "doc_name": self.doc_name,
            "overall_opinion": self.overall_opinion,
            "overall_verdict": self.overall_verdict,
            "overall_score": self.overall_score,
            "per_dimension": {
                dim: [o.to_dict() for o in ops]
                for dim, ops in self.per_dimension.items()
            },
            "critical_issues": self.critical_issues,
            "recommendations": self.recommendations,
            "need_human_review": self.need_human_review,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
        }


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_json_response(text: str, *, strict: bool = False) -> dict[str, Any]:
    """从 LLM 输出里提取首个 JSON 对象。

    支持：
    - ```json ... ``` 围栏
    - 直接 `{...}`
    - 文本中夹带的 JSON 块（找首个平衡的 `{...}`）

    `strict=True` 时无法解析就抛 ValueError；否则返回 {}。
    """
    if not text:
        if strict:
            raise ValueError("空响应")
        return {}

    m = _JSON_FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)

    if strict:
        raise ValueError(f"无法从响应中提取 JSON: {text[:200]}")
    return {}


class BaseAgent:
    """所有维度 Agent 的基类。"""

    dimension: str = ""

    def __init__(
        self,
        provider: LLMProvider,
        text_model: str,
        *,
        temperature: float = 0.0,
    ) -> None:
        self.provider = provider
        self.text_model = text_model
        self.temperature = temperature

    def run(self, *args, **kwargs) -> AgentResult:  # pragma: no cover
        raise NotImplementedError
