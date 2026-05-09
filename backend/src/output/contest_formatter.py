"""赛题格式转换器：AgentResult → 赛题要求的 JSON 格式。

维度映射（当前8维度 → 赛题5维度）：
  C1_structure          → structure
  C2_content_completeness → content
  C3_language           → language
  C5_logic              → logic
  E1_staffing           → compliance
  E2_emergency          → compliance
  L2_standards          → compliance
  T1_template           → (模板相关，单独输出)
  T2_format             → (格式相关，单独输出)
  T3_latency            → (效率相关，单独输出)
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

from src.agents.base import AgentResult


# 维度映射表
_DIMENSION_TO_AUDIT: dict[str, str] = {
    "C1_structure": "structure",
    "C2_content_completeness": "content",
    "C3_language": "language",
    "C5_logic": "logic",
    "E1_staffing": "compliance",
    "E2_emergency": "compliance",
    "L2_standards": "compliance",
}


def _get_audit_dimension(dimension: str) -> str:
    """将内部维度映射为赛题审核维度。"""
    return _DIMENSION_TO_AUDIT.get(dimension, dimension)


def _derive_is_problem(verdict: str, findings_count: int) -> bool:
    """根据 verdict 和 findings 数量判断是否有问题。"""
    if verdict == "pass":
        return False
    if verdict in ("fail", "partial"):
        return True
    # uncertain 的情况，如果没 findings 算无问题
    return findings_count > 0


def _derive_problem_type(finding: dict, dimension: str) -> str:
    """从 finding 推断 problem_type。"""
    if finding.get("problem_type"):
        return finding["problem_type"]
    if finding.get("rule_id"):
        # 从 rule_id 推断
        rule_id = finding["rule_id"]
        if "required_modules" in rule_id or "missing_module" in rule_id.lower():
            return "缺少核心模块"
        if "appendix" in rule_id.lower():
            return "附录问题"
        if "hierarchy" in rule_id.lower() or "title_length" in rule_id.lower():
            return "层级结构问题"
        if "reference" in rule_id.lower() or "standard" in rule_id.lower():
            return "引用规范问题"
        if "logic" in rule_id.lower() or "contradiction" in rule_id.lower():
            return "逻辑一致性问题"
        if "staffing" in rule_id.lower() or "patrol" in rule_id.lower():
            return "人员配置问题"
        if "emergency" in rule_id.lower():
            return "应急处置问题"
        if "language" in rule_id.lower() or "grammar" in rule_id.lower():
            return "语言文字问题"
    # 默认类型
    desc = finding.get("description", "")
    if "缺少" in desc or "未找到" in desc or "缺失" in desc:
        return "缺少必要内容"
    if "引用" in desc or "附录" in desc:
        return "引用规范问题"
    if "格式" in desc or "标点" in desc:
        return "格式规范问题"
    return "内容问题"


def _infer_rule_basis(finding: dict, dimension: str) -> str:
    """推断规则依据。"""
    if finding.get("rule_basis"):
        return finding["rule_basis"]

    rule_id = finding.get("rule_id", "")
    # 基于 rule_id 返回通用规则依据
    if dimension == "C1_structure":
        return "依据《作业指导书编制导则》：文档必须包含岗位条件、职责、作业指引、巡检、应急、培训等核心模块"
    if dimension == "C2_content_completeness":
        return "依据《作业指导书编制导则》：内容应完整准确，技术参数正确，引用标准现行有效"
    if dimension == "C3_language":
        return "依据 GB/T 1.1 标准：语句通顺，标点规范，缩略词首次出现应有中文注释"
    if dimension == "C4_reference":
        return "依据《作业指导书编制导则》：正文引用的附录和标准必须有对应章节"
    if dimension == "C5_logic":
        return "依据《作业指导书编制导则》：文档内容应逻辑一致，无矛盾"
    if dimension == "E1_staffing":
        return "依据《油气管道线路完整性管理规范》：人员配置应满足巡线工每3-10公里配1人"
    if dimension == "E2_emergency":
        return "依据《油气管道线路完整性管理规范》：应急处置应遵循'先控源、防扩大、有序疏散抢险'原则"
    if dimension == "L2_standards":
        return "依据《工程建设标准编写规定》：引用的标准必须为现行有效版本"
    return "依据《作业指导书编制导则》"


def to_contest_findings(agent_result: AgentResult) -> list[dict[str, Any]]:
    """将 AgentResult 转换为赛题格式的 findings 列表。"""
    findings = []
    audit_dim = _get_audit_dimension(agent_result.dimension)

    for f in agent_result.findings:
        f_dict = f.to_dict() if hasattr(f, 'to_dict') else f
        is_problem = _derive_is_problem(agent_result.verdict, len(agent_result.findings))
        problem_type = _derive_problem_type(f_dict, agent_result.dimension)
        rule_basis = _infer_rule_basis(f_dict, agent_result.dimension)

        findings.append({
            "audit_dimension": audit_dim,
            "audit_subtype": agent_result.dimension,
            "is_problem": is_problem,
            "problem_type": problem_type,
            "severity": f_dict.get("severity", "medium"),
            "evidence": f_dict.get("evidence") or f_dict.get("anchor_text", ""),
            "rule_basis": f_dict.get("rule_basis") or rule_basis,
            "correction_suggestion": f_dict.get("correction_suggestion", ""),
        })

    return findings


def format_label_result(
    label_result,
    doc_path: str | Path,
    total_pages: int = 0,
    template_appendix_found: bool = False,
    template_compliant: bool | None = None,
) -> dict[str, Any]:
    """
    将 LabelResult 转换为赛题要求格式。

    参数：
        label_result: LabelPipeline.run() 返回的 LabelResult
        doc_path: 文档路径（用于提取格式信息）
        total_pages: 总页数
        template_appendix_found: 附录是否提供了规定模板
        template_compliant: 是否符合模板（None=无模板要求，True/False=符合/不符合）
    """
    path = Path(doc_path)
    doc_format = path.suffix.lower().replace(".", "")

    # 统计问题
    all_findings = []
    for dim_result in label_result.dimensions.values():
        all_findings.extend(to_contest_findings(dim_result))

    # 统计各级别问题
    high_count = sum(1 for f in all_findings if f["severity"] == "high")
    medium_count = sum(1 for f in all_findings if f["severity"] == "medium")
    low_count = sum(1 for f in all_findings if f["severity"] == "low")

    # 判断是否有问题
    has_problems = any(f["is_problem"] for f in all_findings)

    # 计算总体 verdict
    verdicts = [r.verdict for r in label_result.dimensions.values()]
    if "fail" in verdicts:
        overall_verdict = "fail"
    elif "partial" in verdicts:
        overall_verdict = "partial"
    elif all(v == "pass" for v in verdicts):
        overall_verdict = "pass"
    else:
        overall_verdict = "uncertain"

    return {
        "文档基本信息": {
            "文档名称": label_result.doc_name,
            "文档格式": doc_format,
            "总页数": total_pages,
            "审核耗时(秒)": round(label_result.elapsed_seconds, 1),
            "是否使用规定模板": template_compliant if template_compliant is not None else (False if template_appendix_found else None),
            "兼容状态": "兼容" if doc_format == "docx" else "需转换",
        },
        "审核维度": {
            dim: {
                "verdict": r.verdict,
                "score": r.score,
                "confidence": r.confidence,
                "findings": to_contest_findings(r),
            }
            for dim, r in label_result.dimensions.items()
        },
        "问题统计": {
            "高风险问题": high_count,
            "中风险问题": medium_count,
            "低风险问题": low_count,
            "是否需人工复核": any(r.need_human_review for r in label_result.dimensions.values()),
        },
        "总体结论": {
            "verdict": overall_verdict,
            "是否有问题": has_problems,
            "问题总数": len([f for f in all_findings if f["is_problem"]]),
        },
        "raw_dimensions": label_result.to_dict(),  # 保留原始结构
    }
