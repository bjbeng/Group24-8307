"""验证类工具：证据真实性验证、标准版本检查、步骤一致性比对。"""
from __future__ import annotations
import difflib
import re
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING
from .registry import tool
if TYPE_CHECKING:
    from src.store.repository import Repository

_repo: "Repository | None" = None

def set_repo(repo: "Repository") -> None:
    global _repo
    _repo = repo

def _get_repo() -> "Repository":
    if _repo is None:
        raise RuntimeError("Repository 未初始化")
    return _repo

@dataclass
class EvidenceVerification:
    found: bool
    matched_chunk_id: str | None
    similarity: float
    context_snippet: str = ""

@dataclass
class StandardStatus:
    standard_id: str
    exists_in_db: bool
    year: int | None
    latest_year: int | None
    is_possibly_outdated: bool

@dataclass
class ComparisonResult:
    consistent: bool
    similarity_score: float
    body_steps: list[str]
    appendix_steps: list[str]
    missing_in_body: list[str]
    extra_in_body: list[str]

@tool("verify_evidence_in_doc", "Critic 专用：验证 evidence_text 是否真实存在于文档")
def verify_evidence_in_doc(doc_id: str, evidence_text: str) -> dict[str, Any]:
    if not evidence_text or not evidence_text.strip():
        return {"found": False, "matched_chunk_id": None, "similarity": 0.0, "context_snippet": ""}
    results = _get_repo().search_chunks(evidence_text[:100], doc_id=doc_id, top_k=5)
    best_sim = 0.0
    best_id = None
    best_ctx = ""
    probe = evidence_text[:200].lower()
    for r in results:
        content = (r.get("content") or "").lower()
        if probe in content:
            return {
                "found": True,
                "matched_chunk_id": r.get("chunk_id"),
                "similarity": 1.0,
                "context_snippet": r.get("content", "")[:300],
            }
        sim = difflib.SequenceMatcher(None, probe, content[:500]).ratio()
        if sim > best_sim:
            best_sim = sim
            best_id = r.get("chunk_id")
            best_ctx = r.get("content", "")[:300]
    return {
        "found": best_sim >= 0.6,
        "matched_chunk_id": best_id if best_sim >= 0.6 else None,
        "similarity": round(best_sim, 3),
        "context_snippet": best_ctx,
    }

@tool("verify_standard_version", "检查标准号是否在库，是否可能已更新")
def verify_standard_version(standard_id: str) -> dict[str, Any]:
    results = _get_repo().search_standards(standard_id, top_k=3)
    year_match = re.search(r"(\d{4})", standard_id)
    year = int(year_match.group(1)) if year_match else None
    if not results:
        return {
            "standard_id": standard_id, "exists_in_db": False,
            "year": year, "latest_year": None, "is_possibly_outdated": False,
        }
    years_in_db = []
    for r in results:
        sn = r.get("standard_name", "")
        m = re.search(r"(\d{4})", sn)
        if m:
            years_in_db.append(int(m.group(1)))
    latest = max(years_in_db) if years_in_db else year
    outdated = (year is not None and latest is not None and latest > year)
    return {
        "standard_id": standard_id, "exists_in_db": True,
        "year": year, "latest_year": latest, "is_possibly_outdated": outdated,
    }

@tool("compare_emergency_steps", "对比正文应急步骤和附录处置卡的顺序一致性")
def compare_emergency_steps(body_chunk_id: str, appendix_chunk_id: str) -> dict[str, Any]:
    repo = _get_repo()
    body = repo.get_chunk(body_chunk_id)
    appendix = repo.get_chunk(appendix_chunk_id)
    if not body or not appendix:
        return {"consistent": False, "similarity_score": 0.0,
                "body_steps": [], "appendix_steps": [], "missing_in_body": [], "extra_in_body": []}
    step_re = re.compile(r"(?:^|\n)\s*(?:\d+[.、）]\s*|[（(]\d+[）)]\s*|步骤\s*\d+\s*[：:]\s*)(.+)")
    def extract_steps(text: str) -> list[str]:
        return [m.group(1).strip()[:100] for m in step_re.finditer(text)]
    body_steps = extract_steps(body.get("content") or "")
    app_steps = extract_steps(appendix.get("content") or "")
    if not body_steps and not app_steps:
        return {"consistent": True, "similarity_score": 1.0,
                "body_steps": [], "appendix_steps": [], "missing_in_body": [], "extra_in_body": []}
    matcher = difflib.SequenceMatcher(None, body_steps, app_steps)
    sim = matcher.ratio()
    body_set = set(body_steps)
    app_set = set(app_steps)
    return {
        "consistent": sim >= 0.7,
        "similarity_score": round(sim, 3),
        "body_steps": body_steps,
        "appendix_steps": app_steps,
        "missing_in_body": list(app_set - body_set),
        "extra_in_body": list(body_set - app_set),
    }
