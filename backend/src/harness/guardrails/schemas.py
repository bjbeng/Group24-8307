"""Explorer/Critic 输出的 Pydantic schema。"""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, field_validator

class FindingItem(BaseModel):
    severity: Literal["high", "medium", "low"] = "medium"
    description: str = Field(max_length=1000)
    evidence: str = Field(default="", max_length=800)
    rule_id: str | None = None
    chunk_id: str | None = None

class ExplorerOutput(BaseModel):
    verdict_hint: Literal["pass", "partial", "fail", "uncertain"]
    score_hint: int = Field(ge=0, le=12, default=0)
    confidence: int = Field(ge=0, le=100, default=50)
    findings: list[FindingItem] = Field(default_factory=list, max_length=20)
    evidence_refs: list[str] = Field(default_factory=list)
    reasoning: str = Field(default="", max_length=3000)
    role: Literal["explorer_a", "explorer_b"] = "explorer_b"

    @field_validator("findings", mode="before")
    @classmethod
    def coerce_findings(cls, v: object) -> list:
        if not isinstance(v, list):
            return []
        return v

class CriticOutput(BaseModel):
    verdict: Literal["pass", "partial", "fail", "uncertain"]
    score: int = Field(ge=0, le=12, default=0)
    confidence: int = Field(ge=0, le=100, default=50)
    selected_from: Literal["A", "B", "merged", "critic_only"] = "merged"
    evidence_verified: bool = False
    findings: list[FindingItem] = Field(default_factory=list)
    human_review_required: bool = False
    reasoning: str = Field(default="", min_length=0, max_length=5000)
    skill_saved: str | None = None  # save_skill 后写入 skill_id

    @field_validator("findings", mode="before")
    @classmethod
    def coerce_findings(cls, v: object) -> list:
        if not isinstance(v, list):
            return []
        return v

def parse_explorer_output(data: dict) -> ExplorerOutput:
    """宽松解析：字段缺失时使用默认值，不抛异常。"""
    vh = str(data.get("verdict_hint", data.get("verdict", "uncertain"))).lower()
    if vh not in ("pass", "partial", "fail", "uncertain"):
        vh = "uncertain"
    try:
        score = int(data.get("score_hint", data.get("score", 0)))
    except (TypeError, ValueError):
        score = 0
    try:
        conf = int(data.get("confidence", data.get("confidence_hint", 50)))
    except (TypeError, ValueError):
        conf = 50
    raw_findings = data.get("findings", []) or []
    findings = []
    for f in raw_findings:
        if not isinstance(f, dict):
            continue
        sev = str(f.get("severity", "medium")).lower()
        if sev not in ("high", "medium", "low"):
            sev = "medium"
        findings.append(FindingItem(
            severity=sev,
            description=str(f.get("description", ""))[:1000],
            evidence=str(f.get("evidence", ""))[:800],
            rule_id=f.get("rule_id"),
            chunk_id=f.get("chunk_id"),
        ))
    return ExplorerOutput(
        verdict_hint=vh,
        score_hint=max(0, min(12, score)),
        confidence=max(0, min(100, conf)),
        findings=findings[:20],
        evidence_refs=list(data.get("evidence_refs", [])),
        reasoning=str(data.get("reasoning", data.get("details", data.get("notes", ""))))[:3000],
    )

def parse_critic_output(data: dict) -> CriticOutput:
    """宽松解析 Critic 输出。"""
    verdict = str(data.get("verdict", "uncertain")).lower()
    if verdict not in ("pass", "partial", "fail", "uncertain"):
        verdict = "uncertain"
    try:
        score = int(data.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    try:
        conf = int(data.get("confidence", 50))
    except (TypeError, ValueError):
        conf = 50
    selected = str(data.get("selected_from", "merged"))
    if selected not in ("A", "B", "merged", "critic_only"):
        selected = "merged"
    raw_findings = data.get("findings", []) or []
    findings = []
    for f in raw_findings:
        if not isinstance(f, dict):
            continue
        sev = str(f.get("severity", "medium")).lower()
        if sev not in ("high", "medium", "low"):
            sev = "medium"
        findings.append(FindingItem(
            severity=sev,
            description=str(f.get("description", ""))[:1000],
            evidence=str(f.get("evidence", ""))[:800],
            rule_id=f.get("rule_id"),
            chunk_id=f.get("chunk_id"),
        ))
    return CriticOutput(
        verdict=verdict,
        score=max(0, min(12, score)),
        confidence=max(0, min(100, conf)),
        selected_from=selected,
        evidence_verified=bool(data.get("evidence_verified", False)),
        findings=findings,
        human_review_required=bool(data.get("human_review_required", False)) or verdict == "uncertain",
        reasoning=str(data.get("reasoning", data.get("details", "")))[:5000],
        skill_saved=data.get("skill_saved"),
    )
