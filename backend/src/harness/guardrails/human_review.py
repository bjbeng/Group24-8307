"""人工复核触发逻辑。"""
from __future__ import annotations
from typing import Any

def should_human_review(result_dict: dict[str, Any], dimension: str = "") -> bool:
    """根据审核结果判断是否需要人工复核。"""
    if result_dict.get("verdict") == "uncertain":
        return True
    if not result_dict.get("evidence_verified", True):
        return True
    confidence = result_dict.get("confidence", 100)
    if isinstance(confidence, (int, float)) and confidence < 50:
        return True
    if result_dict.get("selected_from") == "critic_only":
        return True
    # 维度专属阈值
    extra = result_dict.get("extra") or {}
    if dimension == "E1_staffing":
        if extra.get("rules_passed", 99) <= 2:
            return True
    if dimension == "E2_emergency":
        if (extra.get("coverage_rate", 1.0) or 1.0) < 0.4:
            return True
    findings = result_dict.get("findings") or []
    high_count = sum(1 for f in findings if isinstance(f, dict) and f.get("severity") == "high")
    if high_count >= 3:
        return True
    return bool(result_dict.get("human_review_required", False))

def cross_dim_consistency_check(all_results: dict[str, dict[str, Any]]) -> list[str]:
    """跨维度矛盾检查；返回警告消息列表。"""
    warnings: list[str] = []
    c1 = all_results.get("C1_structure", {})
    c4 = all_results.get("C4_reference", {})
    if c1.get("verdict") == "pass" and c4.get("verdict") == "fail":
        warnings.append("C1 pass 但 C4 fail（存在悬空引用），C1 置信度降级")
    l2 = all_results.get("L2_standards", {})
    c2 = all_results.get("C2_content_completeness", {})
    if l2.get("verdict") == "pass" and c2.get("verdict") == "fail":
        warnings.append("L2 标准引用通过但 C2 内容不完整，需人工核查")
    return warnings
