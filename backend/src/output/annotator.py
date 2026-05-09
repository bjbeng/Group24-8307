"""带批注 DOCX 输出 + Markdown 概况报告。

批注颜色约定：
  HIGH    → 红色 (#FF0000)
  MEDIUM  → 黄色 (#FFC000)
  LOW     → 绿色 (#92D050)
  uncertain → 蓝色 (#4472C4)

定位策略：
  1. 先按 chunk.anchor_text 在段落中找最佳匹配（SequenceMatcher）
  2. 找不到时按 chunk.paragraph_index 回退
  3. 还找不到就批注到文档末尾
"""
from __future__ import annotations

import datetime
import difflib
import io
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# 颜色映射
_SEVERITY_COLORS = {
    "high":      "FF0000",  # 红
    "medium":    "FFC000",  # 黄
    "low":       "92D050",  # 绿
    "uncertain": "4472C4",  # 蓝
}
_VERDICT_EMOJI = {
    "pass": "✅", "partial": "⚠️", "fail": "❌", "uncertain": "❓"
}


@dataclass
class AnnotationTarget:
    """定位到具体段落的注解目标。"""
    paragraph_index: int
    anchor_text: str
    comment_text: str
    color: str
    dimension: str
    severity: str
    section_path: str = ""


def _find_best_paragraph(paragraphs: list[Any], anchor: str, fallback_idx: int, *, section_path: str = "") -> int:
    """在所有段落中找与 anchor 最相似的那一个，返回其索引。

    优先策略：
    1. 如果有 section_path，按 section_path 在段落文本中找标题匹配
    2. anchor 完全包含在段落中（子串匹配）
    3. SequenceMatcher 相似度匹配
    """
    if not anchor and not section_path:
        return min(fallback_idx, len(paragraphs) - 1) if paragraphs else 0

    # 优先用 section_path + anchor 组合定位
    if section_path:
        # 在段落中找包含 section_path 标题的匹配
        section_short = section_path.split(".")[-1] if "." in section_path else section_path
        for i, para in enumerate(paragraphs):
            text = para.text
            if section_path in text or section_short in text:
                return i

    anchor_low = anchor.lower()[:80] if anchor else ""
    best_idx = fallback_idx
    best_score = 0.0

    for i, para in enumerate(paragraphs):
        text = para.text.lower()[:200]
        if anchor_low and anchor_low in text:
            return i
        if anchor_low:
            score = difflib.SequenceMatcher(None, anchor_low, text[:len(anchor_low) + 40]).ratio()
            if score > best_score:
                best_score = score
                best_idx = i

    return min(best_idx, len(paragraphs) - 1) if paragraphs else 0


def _add_comment_xml(doc: Any, para: Any, text: str, author: str = "AI 审核") -> None:
    """
    通过底层 XML 操作在指定段落插入 Word 批注。
    python-docx 没有公开的 Comment API，用 lxml 直接操作。
    """
    from lxml import etree
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    # 获取或创建 comments part
    try:
        comments_part = doc.part.comments_part
        comments_el = comments_part._element
    except AttributeError:
        # 创建 comments.xml
        from docx.opc.part import Part
        from docx.opc.packuri import PackURI
        from docx.opc.constants import RELATIONSHIP_TYPE as RT

        comments_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:comments xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas"'
            ' xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
            ' xmlns:o="urn:schemas-microsoft-com:office:office"'
            ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
            ' xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'
            ' xmlns:v="urn:schemas-microsoft-com:vml"'
            ' xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing"'
            ' xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
            ' xmlns:w10="urn:schemas-microsoft-com:office:word"'
            ' xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
            ' xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"'
            ' xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml"'
            ' xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml/extras"'
            ' xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"'
            ' mc:Ignorable="w14 w15 wp14"></w:comments>'
        )
        part = Part(
            PackURI("/word/comments.xml"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml",
            comments_xml.encode("utf-8"),
            doc.part.package,
        )
        doc.part.relate_to(part, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments")
        comments_el = etree.fromstring(comments_xml.encode("utf-8"))

    # 生成唯一 comment id
    existing = comments_el.findall(qn("w:comment"))
    cid = str(len(existing))
    now_str = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

    # 构建 <w:comment> 元素
    comment = OxmlElement("w:comment")
    comment.set(qn("w:id"), cid)
    comment.set(qn("w:author"), author)
    comment.set(qn("w:date"), now_str)

    comment_para = OxmlElement("w:p")
    comment_run = OxmlElement("w:r")
    comment_text_el = OxmlElement("w:t")
    comment_text_el.text = text
    comment_run.append(comment_text_el)
    comment_para.append(comment_run)
    comment.append(comment_para)
    comments_el.append(comment)

    # 在段落中插入批注引用标记
    p = para._p
    # commentRangeStart
    cs = OxmlElement("w:commentRangeStart")
    cs.set(qn("w:id"), cid)
    p.insert(0, cs)
    # commentRangeEnd
    ce = OxmlElement("w:commentRangeEnd")
    ce.set(qn("w:id"), cid)
    p.append(ce)
    # commentReference run
    cr_run = OxmlElement("w:r")
    cr_ref = OxmlElement("w:commentReference")
    cr_ref.set(qn("w:id"), cid)
    cr_run.append(cr_ref)
    p.append(cr_run)


def annotate_docx(
    src_path: str | Path,
    audit_result: dict[str, Any],
    out_path: str | Path,
) -> Path:
    """
    在原文档的对应段落插入批注，写出带批注的 DOCX。

    audit_result: AuditResult.to_dict() 格式
    """
    try:
        from docx import Document
    except ImportError:
        raise RuntimeError("python-docx 未安装：pip install python-docx")

    doc = Document(str(src_path))
    paragraphs = doc.paragraphs
    n = len(paragraphs)

    dimensions: dict[str, Any] = audit_result.get("dimensions", {})

    targets: list[AnnotationTarget] = []
    for dim_name, dim_data in dimensions.items():
        if not isinstance(dim_data, dict):
            continue
        verdict = dim_data.get("verdict", "uncertain")
        findings = dim_data.get("findings") or []

        for f in findings:
            if not isinstance(f, dict):
                continue
            sev = f.get("severity", "medium")
            color = _SEVERITY_COLORS.get(sev, _SEVERITY_COLORS["medium"])

            chunk_id = f.get("chunk_id") or ""
            section_path = f.get("section_path", "") or ""
            anchor = f.get("anchor_text", "")[:60] or f.get("evidence", "")[:60] or ""
            para_idx = 0
            if chunk_id:
                # chunk_id 格式: {doc_id}__{section_path}__{type}__{seq}
                # 尝试从数字序号推断段落位置
                parts = chunk_id.split("__")
                if len(parts) >= 4:
                    try:
                        seq = int(parts[-1]) - 1
                        para_idx = min(seq * 3, n - 1)
                    except (ValueError, IndexError):
                        pass

            comment_text = (
                f"[{dim_name} | {sev.upper()}] {f.get('description', '')}"
            )
            if f.get("rule_id"):
                comment_text += f" ({f['rule_id']})"

            targets.append(AnnotationTarget(
                paragraph_index=para_idx,
                anchor_text=anchor,
                comment_text=comment_text,
                color=color,
                dimension=dim_name,
                severity=sev,
                section_path=section_path,
            ))

        # 对 need_human_review 的维度，在文档头部加蓝色总注
        if dim_data.get("need_human_review") and not findings:
            targets.append(AnnotationTarget(
                paragraph_index=0,
                anchor_text="",
                comment_text=f"[{dim_name} | UNCERTAIN] {dim_data.get('details', '需人工复核')}",
                color=_SEVERITY_COLORS["uncertain"],
                dimension=dim_name,
                severity="uncertain",
                section_path="",
            ))

    # 按段落位置排序，避免 XML 插入顺序混乱
    targets.sort(key=lambda t: t.paragraph_index)

    added = 0
    for target in targets:
        idx = _find_best_paragraph(paragraphs, target.anchor_text, target.paragraph_index, section_path=section_path)
        if idx >= n:
            idx = n - 1
        if n == 0:
            break
        try:
            _add_comment_xml(doc, paragraphs[idx], target.comment_text)
            added += 1
        except Exception as e:
            log.warning("批注插入失败 [%s]: %s", target.dimension, e)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    log.info("带批注 DOCX 已写出: %s（%d 条批注）", out, added)
    return out


# 维度到审核类别的分组映射
_CONTENT_DIMS = [
    ("C1_structure",  "1.1 结构完整性"),
    ("C2_content",    "1.2 内容准确性"),
    ("C3_language",   "1.3 文字语法"),
    ("C4_reference",  "1.4 引用文件可追溯性"),
    ("C5_logic",      "1.5 业务逻辑"),
]
_DEEP_DIMS = [
    ("E1_staffing",   "2.1 人员配备审核"),
    ("E2_emergency",  "2.2 应急处置审核"),
]
_TEMPLATE_DIMS = [
    ("T1_template",   "3.1 模板使用"),
    ("T2_format",     "3.2 格式兼容性"),
    ("T3_efficiency", "3.3 识别效率"),
]

_DEEP_HEADER = """## 第二部分 · 深度审核问题

涵盖人员配备审核、应急处置审核两个子项。

"""
_TMPL_HEADER = """## 第三部分 · 模板检测问题

检查是否使用规定模板，以及格式兼容性和识别效率。

"""

_SEVERITY_LABEL = {
    "high":   "🔴 高风险",
    "medium": "🟡 中风险",
    "low":    "🟢 低风险",
}


def _sort_key_section(finding: dict[str, Any]) -> tuple[int, str]:
    """按 section_path 自然升序，无 section_path 的排末尾。"""
    sp = finding.get("section_path", "") or ""
    if not sp:
        return (1, "")
    return (0, sp)


def _render_findings_section(
    dim_key: str,
    dim_label: str,
    dimensions: dict[str, Any],
) -> list[str]:
    """渲染单个子维度的问题列表。"""
    lines: list[str] = [f"### {dim_label}"]
    dim_data = dimensions.get(dim_key)
    if not dim_data or not isinstance(dim_data, dict):
        lines += ["", "（未执行该维度审核）", ""]
        return lines

    verdict = dim_data.get("verdict", "uncertain")
    findings = [f for f in (dim_data.get("findings") or []) if isinstance(f, dict)]

    # 对于 metrics 类维度（无 findings 字段），展示 verdict 说明
    if not findings:
        emoji = _VERDICT_EMOJI.get(verdict, "❓")
        details = dim_data.get("details", "")
        lines.append("")
        if verdict == "pass":
            lines.append(f"审核结论：{emoji} 通过。{details}")
        else:
            lines.append(f"审核结论：{emoji} {verdict}。{details or '无具体问题记录。'}")
        lines.append("")
        return lines

    findings_sorted = sorted(findings, key=_sort_key_section)
    lines.append("")
    for f in findings_sorted:
        sp = f.get("section_path", "") or ""
        position = f"第 {sp} 节" if sp else "全文"
        desc = f.get("description", "（无描述）")
        sev = f.get("severity", "medium")
        sev_label = _SEVERITY_LABEL.get(sev, f"⬜ {sev}")
        rule = f.get("rule_id", "")
        rule_suffix = f"（{rule}）" if rule else ""
        lines.append(f"- **位置**：{position}")
        lines.append(f"  **描述**：{desc}{rule_suffix}")
        lines.append(f"  **风险等级**：{sev_label}")
        lines.append("")

    return lines


def _render_audit_opinions_section(
    dim_key: str,
    dim_label: str,
    audit_report: dict[str, Any],
) -> list[str]:
    """渲染单个维度的 LLM 审核意见（audit_report.per_dimension）。

    当 audit_report 存在时优先使用此函数，展示 LLM 生成的人工可读意见。
    """
    lines: list[str] = [f"### {dim_label}"]
    per_dim: dict[str, Any] = audit_report.get("per_dimension", {})
    opinions = per_dim.get(dim_key, [])

    if not opinions:
        lines += ["", "（该维度无审核意见）", ""]
        return lines

    lines.append("")
    for op in opinions:
        sev = op.get("severity", "medium")
        sev_label = _SEVERITY_LABEL.get(sev, f"⬜ {sev}")
        verdict = op.get("verdict", "uncertain")
        emoji = _VERDICT_EMOJI.get(verdict, "❓")

        check_item = op.get("check_item", "")
        lines.append(f"- **{check_item}** {emoji} {sev_label}")
        opinion = op.get("opinion", "")
        if opinion:
            lines.append(f"  - **意见**：{opinion}")

        evidence = op.get("evidence_summary", "")
        if evidence:
            lines.append(f"  - **依据**：{evidence}")

        suggestions = op.get("suggestions") or []
        if suggestions:
            lines.append("  - **修改建议**：")
            for s in suggestions:
                lines.append(f"    - {s}")

        lines.append("")

    return lines


def _dim_renderer(
    dim_key: str,
    dim_label: str,
    audit_result: dict[str, Any],
) -> list[str]:
    """为有 audit_report 的维度优先渲染 LLM 意见，否则退化到 findings。"""
    ar = audit_result.get("audit_report")
    if ar and isinstance(ar, dict):
        per_dim: dict[str, Any] = ar.get("per_dimension", {})
        if per_dim.get(dim_key):
            return _render_audit_opinions_section(dim_key, dim_label, ar)
    return _render_findings_section(dim_key, dim_label, audit_result.get("dimensions", {}))


def generate_markdown_report(audit_result: dict[str, Any]) -> str:
    """生成结构化三部分审核报告（Markdown）。

    优先使用 LLM 生成的人工可读意见（audit_report.per_dimension），
    无 audit_report 时退化到原始 findings。
    """
    doc_name = audit_result.get("doc_name", "未知文档")
    doc_id = audit_result.get("doc_id", "")
    ts = audit_result.get("review_timestamp", "")[:19].replace("T", " ")
    overall = audit_result.get("overall_verdict", "uncertain")
    score = audit_result.get("overall_score", 0)
    elapsed = audit_result.get("elapsed_seconds", 0)
    need_review = audit_result.get("need_human_review", False)
    doc_summary = audit_result.get("doc_summary", "")
    dimensions: dict[str, Any] = audit_result.get("dimensions", {})
    audit_report: dict[str, Any] | None = audit_result.get("audit_report")

    # 统计各级别问题（优先用 audit_report.critical_issues + recommendations count）
    if audit_report and isinstance(audit_report, dict):
        high_count = len(audit_report.get("critical_issues") or [])
        recs = audit_report.get("recommendations") or []
        medium_count = len([r for r in recs if r])
        low_count = 0
    else:
        high_count = medium_count = low_count = 0
        for dim_data in dimensions.values():
            if not isinstance(dim_data, dict):
                continue
            for f in (dim_data.get("findings") or []):
                if isinstance(f, dict):
                    sev = f.get("severity", "")
                    if sev == "high":
                        high_count += 1
                    elif sev == "medium":
                        medium_count += 1
                    elif sev == "low":
                        low_count += 1

    verdict_emoji = _VERDICT_EMOJI.get(overall, "❓")

    # 总体意见（来自 audit_report）
    overall_opinion = ""
    if audit_report and isinstance(audit_report, dict):
        overall_opinion = audit_report.get("overall_opinion", "")

    lines: list[str] = [
        f"# {doc_name} 审核报告",
        "",
        # ── 审核概况 ──────────────────────────────────────────────────────────
        "## 审核概况",
        "",
        "| 字段 | 内容 |",
        "|------|------|",
        f"| **文档名称** | {doc_name} |",
        f"| **文档内容** | {doc_summary or '（未能提取摘要）'} |",
        f"| **审核时长** | {elapsed:.1f} 秒 |",
        f"| **高风险问题** | {high_count} 项 |",
        f"| **中风险问题** | {medium_count} 项 |",
        f"| **低风险问题** | {low_count} 项 |",
        f"| **总体结论** | {verdict_emoji} **{overall.upper()}** |",
        f"| **总分** | {score} |",
        f"| **需人工复核** | {'是 ⚠️' if need_review else '否'} |",
        "",
        f"> 文档 ID：`{doc_id}` | 审核时间：{ts}",
        "",
    ]

    if overall_opinion:
        lines += [
            "",
            f"> **总体意见**：{overall_opinion}",
            "",
        ]

    lines += ["---", ""]

    # ── 第一部分：内容审核问题（优先用 audit_report）─────────────────────
    lines += [
        "## 第一部分 · 内容审核问题",
        "",
        "涵盖结构完整性、内容准确性、文字语法、引用文件可追溯性、业务逻辑五个子项。",
        "",
    ]

    for dim_key, dim_label in _CONTENT_DIMS:
        lines.extend(_dim_renderer(dim_key, dim_label, audit_result))

    lines += ["---", "", _DEEP_HEADER]

    for dim_key, dim_label in _DEEP_DIMS:
        lines.extend(_dim_renderer(dim_key, dim_label, audit_result))

    lines += ["---", "", _TMPL_HEADER]

    for dim_key, dim_label in _TEMPLATE_DIMS:
        lines.extend(_dim_renderer(dim_key, dim_label, audit_result))

    # ── 总体改进建议（来自 audit_report）─────────────────────────────────
    if audit_report and isinstance(audit_report, dict):
        recommendations = audit_report.get("recommendations") or []
        if recommendations:
            lines += [
                "---",
                "",
                "## 总体改进建议",
                "",
            ]
            for i, rec in enumerate(recommendations, 1):
                lines.append(f"{i}. {rec}")
            lines.append("")

    lines += [
        "---",
        f"*本报告由 IndustryAgent AI 审核系统自动生成 | {ts}*",
    ]

    return "\n".join(lines)


def write_outputs(
    src_docx: str | Path,
    audit_result: dict[str, Any],
    out_dir: str | Path,
) -> dict[str, Path]:
    """
    一次性写出三种产物：
      - {doc_id}_audit.json      机读结果
      - {doc_id}_report.md       人读报告
      - {doc_id}_annotated.docx  带批注原文
    返回 {type: Path} 字典。
    """
    import json as _json

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    doc_id = audit_result.get("doc_id", "unknown")

    # 1. JSON
    json_path = out / f"{doc_id}_audit.json"
    json_path.write_text(_json.dumps(audit_result, ensure_ascii=False, indent=2), encoding="utf-8")

    # 2. Markdown
    md_path = out / f"{doc_id}_report.md"
    md_path.write_text(generate_markdown_report(audit_result), encoding="utf-8")

    # 3. 带批注 DOCX（仅支持 .docx 输入）
    src = Path(src_docx)
    results = {"json": json_path, "markdown": md_path}
    if src.suffix.lower() in (".docx", ".docm"):
        annotated_path = out / f"{doc_id}_annotated.docx"
        try:
            annotate_docx(src, audit_result, annotated_path)
            results["annotated_docx"] = annotated_path
        except Exception as e:
            log.warning("带批注 DOCX 生成失败（不影响其他输出）: %s", e)
    else:
        log.info("源文件为 %s，跳过带批注 DOCX 生成（仅支持 .docx）", src.suffix)

    return results
