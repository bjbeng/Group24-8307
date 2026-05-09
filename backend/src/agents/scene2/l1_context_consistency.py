"""L1 上下文一致性 —— 跨章节抽取并比对。

区段负责人姓名在不同位置写法不一（表中「专职区长姓名」列、人防里「专职区（段）长」等），
单靠 ``区段长：`` 一种正则会经常抽不到。**策略**：多模式正则兜底 + （有 provider 时）**整段摘录送 LLM
专门抽人名**，再合并去重做一致性判断——**不是「先正则再只把正则结果给后面的 LLM」**；
人防那一段 LLM 仍独立做段落一致性。

CPY 类工程编号与其它逻辑不变。
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any, Iterable

from src.agents.base import AgentResult, BaseAgent, Finding, parse_json_response
from src.agents.llm_audit_utils import build_json_only_system
from src.llm import Message
from src.llm.provider import LLMProvider


log = logging.getLogger(__name__)

_DIM = "L1_context_consistency"

RE_HCA_PIPELINE = re.compile(
    r"(CPY-\d{3,4}(?:-[A-Z0-9]{2,20})*)",
    re.IGNORECASE,
)
RE_STAKE = re.compile(r"K\d{1,4}[+＋]\d{1,4}")

_LEADER_NEEDLES = (
    "专职区长", "专职区段长", "专职区（段）长", "专职区(段)长",
    "区段长", "区（段）长", "区(段)长",
)

_SPLIT_MARKERS = ("高后果区基本信息", "基本信息", "人防", "人防管控", "风险评价")


def _extract_leaders_regex(text: str) -> list[str]:
    """多模式匹配区段负责人中文姓名（2～4 字），去重保序。"""
    if not text:
        return []

    patterns: list[re.Pattern[str]] = [
        # 表头式：专职区长姓名 / 专职区段长姓名 后跟人名（同格、冒号或空白）
        re.compile(
            r"专职区(?:段)?长姓名\s*[：:：]?\s*([\u4e00-\u9fa5]{2,4})(?![\u4e00-\u9fff])",
        ),
        # 人防/正文：专职区（段）长、专职区段长、专职区长 + 标点 + 姓名
        re.compile(
            r"专职区(?:[（(]段[）)]|段)?长\s*[：:是为]\s*([\u4e00-\u9fa5]{2,4})(?![\u4e00-\u9fff])",
        ),
        re.compile(
            r"专职区(?:[（(]段[）)]|段)?长[，,\s]+\s*([\u4e00-\u9fa5]{2,4})(?![\u4e00-\u9fff])",
        ),
        # 人防常见：专职区（段）长  李伟负责 / 为 / 担任
        re.compile(
            r"专职区(?:[（(]段[）)]|段)?长\s{1,12}([\u4e00-\u9fa5]{2,4})\s*(?:负责|为|担任)",
        ),
        # 仅有空白且姓名后接标点或行尾（避免吞掉「负责」）
        re.compile(
            r"专职区(?:[（(]段[）)]|段)?长\s{1,12}([\u4e00-\u9fa5]{2,4})(?=\s*[，,。；、\n\r]|$)",
        ),
        # 简明：区段长 / 区（段）长
        re.compile(r"区[（(]段[）)]?长\s*[：:]\s*([\u4e00-\u9fa5]{2,4})(?![\u4e00-\u9fff])"),
        re.compile(r"区段长\s*[：:]\s*([\u4e00-\u9fa5]{2,4})(?![\u4e00-\u9fff])"),
    ]

    seen: dict[str, None] = {}
    for pat in patterns:
        for m in pat.finditer(text):
            name = m.group(1).strip()
            # 剔除明显非人名占位
            if name in {"姓名", "名称", "签字", "签章", "日期", "单位"}:
                continue
            if name not in seen:
                seen[name] = None
    return list(seen.keys())


def _leader_excerpt_for_llm(full_text: str, max_chars: int = 9000) -> str:
    """围绕「区长/段长」相关词截取，避免把整个几百 KB 塞进 LLM。"""
    if len(full_text) <= max_chars:
        return full_text
    spans: list[tuple[int, int]] = []
    for kw in _LEADER_NEEDLES:
        idx = -1
        while True:
            idx = full_text.find(kw, idx + 1)
            if idx < 0:
                break
            spans.append((max(0, idx - 320), min(len(full_text), idx + 480)))
    if not spans:
        return full_text[:max_chars]
    merged = _merge_spans_cover(full_text, spans, max_chars)
    return merged or full_text[:max_chars]


def _merge_spans_cover(full_text: str, spans: list[tuple[int, int]], budget: int) -> str:
    covered = [False] * len(full_text)
    for a, b in spans:
        for i in range(a, b):
            covered[i] = True
    out: list[str] = []
    i = 0
    left = budget
    while i < len(full_text) and left > 0:
        if not covered[i]:
            i += 1
            continue
        start = i
        while i < len(full_text) and covered[i]:
            i += 1
        seg = full_text[start:i]
        if len(seg) > left:
            out.append(seg[:left])
            break
        out.append(seg)
        left -= len(seg)
    return "\n...\n".join(out)


def _merge_full_text(chunks: list[dict[str, Any]]) -> str:
    pieces: list[str] = []
    for c in chunks:
        title = (c.get("title") or "").strip()
        body = (c.get("content") or "").strip()
        if title:
            pieces.append(title)
        if body:
            pieces.append(body)
    return "\n".join(pieces)


def _doc_id_fallback_code(doc_id: str) -> str | None:
    compact = doc_id.replace("_", "")
    m = RE_HCA_PIPELINE.search(compact.upper())
    if not m:
        return None
    return m.group(1).upper()


def _normalize_pipeline_codes(matches: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(m.upper() for m in matches))


def _excerpt_for_llm(full_text: str, max_chars: int = 4500) -> str:
    if len(full_text) <= max_chars:
        return full_text
    spans: list[tuple[int, int]] = []
    for kw in _SPLIT_MARKERS:
        idx = full_text.find(kw)
        if idx >= 0:
            spans.append((max(0, idx - 400), min(len(full_text), idx + 1200)))
    if not spans:
        return full_text[:max_chars]
    merged = _merge_spans_cover(full_text, spans, max_chars)
    return merged or full_text[:max_chars]


def _extract_leaders_llm(
    provider: LLMProvider,
    model: str,
    excerpt: str,
    temperature: float,
) -> tuple[list[str], str]:
    """让 LLM 只抽人名；返回 (姓名列表, 原始说明)。"""
    sys = build_json_only_system(
        "你是油气管道行政管理文档抽取助手。"
        "任务：在给定摘录中找出「区段长、专职区段长、专职区长」等岗位职责对应的具体人员中文姓名。"
        "表头可能出现「专职区长姓名」「专职区段长姓名」列，人防措施里可能出现「专职区（段）长」——"
        "只输出真实姓名（2～4 个汉字），不要输出职务词本身。"
        "若摘录中多处出现同名只保留一份；若没有明确人名输出空数组。"
    )
    user = (
        "## 摘录\n"
        f"{excerpt[:8000]}\n\n"
        "只输出 JSON：`{\"names\":[\"张三\",\"…\"],\"note\":\"可选一句说明\"}`"
    )
    raw = provider.call_text(
        [Message(role="system", content=sys), Message(role="user", content=user)],
        model=model,
        temperature=temperature,
        max_tokens=500,
    )
    data = parse_json_response(raw) or {}
    names = data.get("names")
    note = str(data.get("note") or "")
    if not isinstance(names, list):
        return [], note
    cleaned: list[str] = []
    for n in names:
        if isinstance(n, str) and len(n) >= 2 and all("\u4e00" <= c <= "\u9fff" for c in n):
            if n not in cleaned and n not in {"姓名", "名称", "签章"}:
                cleaned.append(n[:4])
    return cleaned, note


def _merge_unique_names(regex_names: list[str], llm_names: list[str]) -> list[str]:
    out: dict[str, None] = {}
    for n in regex_names + llm_names:
        if n and n not in out:
            out[n] = None
    return list(out.keys())


class L1ContextConsistencyAgent(BaseAgent):
    dimension = _DIM

    def __init__(
        self,
        provider: LLMProvider | None = None,
        text_model: str = "",
        *,
        repo: Any | None = None,
        temperature: float = 0.0,
    ) -> None:
        super().__init__(provider, text_model or "unused", temperature=temperature)
        self.repo = repo

    def run(self, chunks: list[dict[str, Any]]) -> AgentResult:
        findings: list[Finding] = []
        full_text = _merge_full_text(chunks)
        doc_id = (chunks[0].get("doc_id") if chunks else "") or ""
        id_fallback = _doc_id_fallback_code(doc_id)

        if not full_text.strip():
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain", score=0, confidence=15,
                details="无文本可审。", need_human_review=True,
            )

        leaders_regex = _extract_leaders_regex(full_text)
        leaders_llm: list[str] = []
        leader_llm_note = ""
        leaders_from_llm_attempt = False

        if self.provider and self.text_model:
            excerpt_lead = _leader_excerpt_for_llm(full_text)
            leaders_from_llm_attempt = True
            try:
                leaders_llm, leader_llm_note = _extract_leaders_llm(
                    self.provider, self.text_model, excerpt_lead, self.temperature
                )
            except Exception as e:
                log.warning("L1 区段长 LLM 抽取失败: %s", e)

        merged_leaders = _merge_unique_names(leaders_regex, leaders_llm)

        if merged_leaders:
            ctr = Counter(merged_leaders)
            if len(merged_leaders) > 1:
                findings.append(Finding(
                    severity="medium",
                    description=(
                        f"文档中区段长/专职区（段）长对应姓名出现多套："
                        f"{merged_leaders}，请核对表与人防措辞是否同人"
                    ),
                    evidence=str(list(ctr.items())),
                    rule_id="L1.leader_inconsistent",
                ))
        elif any(k in full_text for k in _LEADER_NEEDLES):
            findings.append(Finding(
                severity="low",
                description=(
                    "文中出现区长/段长相关职务表述，但未可靠抽取到人名。"
                    "可能为表格换行或非标准排版，建议人工或对扫描件做 OCR。"
                ),
                evidence="regex+LLM均无姓名",
                rule_id="L1.leader_extract_uncertain",
            ))

        pipeline_codes = _normalize_pipeline_codes(RE_HCA_PIPELINE.findall(full_text))
        if id_fallback:
            pipeline_codes = _normalize_pipeline_codes([*pipeline_codes, id_fallback])
        if len(pipeline_codes) > 1:
            findings.append(Finding(
                severity="medium",
                description=(
                    "全文出现多个互不相同的 CPY 类编号，请核对是否正确："
                    f"{pipeline_codes}"
                ),
                evidence=", ".join(pipeline_codes),
                rule_id="L1.pipeline_code_multiple",
            ))

        has_basic = (
            "基本信息" in full_text or "高后果区基本情况" in full_text
        )
        has_risk_eval = "风险评价" in full_text
        has_civil = (
            "人防" in full_text or "人防管控" in full_text or "人防措施" in full_text
        )

        if has_basic and has_risk_eval:
            findings.append(Finding(
                severity="low",
                description=(
                    "文档同时含基本情况与「风险评价」内容，管线位置/HCA编号/等级"
                    "是否与评价小节一致需在表级人工或结构化对齐（纯文本规则无法穷尽）。"
                ),
                evidence="",
                rule_id="L1.manual_verify_basic_vs_risk_evaluation",
            ))

        if self.provider and self.text_model and has_basic and has_civil:
            excerpt = _excerpt_for_llm(full_text)
            sys = build_json_only_system(
                "你是高后果区方案一致性审核员。只依据摘录判断：人防管控或人防措施中提到的"
                "区段名称、管线位置、高后果区编号，是否与「基本信息」小节一致。"
                "摘录未写明则视为无法判断。"
            )
            user = (
                "## 摘录\n"
                f"{excerpt[:5000]}\n\n"
                "只输出一个 JSON 对象，字段：consistent（bool）、details（str）、"
                "findings（数组，元素含 severity/description）。无矛盾时 findings 为空数组。"
            )
            try:
                raw = self.provider.call_text(
                    [
                        Message(role="system", content=sys),
                        Message(role="user", content=user),
                    ],
                    model=self.text_model,
                    temperature=self.temperature,
                    max_tokens=600,
                )
                data = parse_json_response(raw) or {}
                if data.get("consistent") is False:
                    inner = data.get("findings")
                    desc_main = data.get("details") or "人防表述与基本信息可能不一致"
                    if isinstance(inner, list) and inner:
                        for item in inner:
                            if isinstance(item, dict):
                                findings.append(Finding(
                                    severity=str(item.get("severity") or "medium"),
                                    description=str(item.get("description") or ""),
                                    evidence=str(data.get("details", "")),
                                    rule_id="L1.civil_defense_basic_inconsistent_llm",
                                ))
                    else:
                        findings.append(Finding(
                            severity="medium",
                            description=str(desc_main),
                            evidence=str(data.get("details", "")),
                            rule_id="L1.civil_defense_basic_inconsistent_llm",
                        ))
            except Exception as e:
                log.warning("L1 LLM cross-check skipped: %s", e)

        stakes = list(dict.fromkeys(RE_STAKE.findall(full_text)))

        high = any(f.severity == "high" for f in findings)
        if high:
            verdict, score, conf = "fail", 4, 70
        elif findings:
            verdict, score, conf = "partial", 7, 75
        else:
            verdict, score, conf = "pass", 10, 85

        return AgentResult(
            dimension=self.dimension,
            verdict=verdict, score=score, confidence=conf,
            findings=findings,
            details=(
                f"区段长合并去重 {len(merged_leaders)}（正则{len(leaders_regex)} + "
                f"LLM{len(leaders_llm)}）；"
                f"CPY 编号 {pipeline_codes or id_fallback or '—'}；桩号数 {len(stakes)}。"
            ),
            extra={
                "section_leaders_regex": leaders_regex,
                "section_leaders_llm": leaders_llm,
                "section_leaders_merged": merged_leaders,
                "leader_llm_note": leader_llm_note,
                "leader_llm_attempted": leaders_from_llm_attempt,
                "hca_pipeline_codes": pipeline_codes if pipeline_codes else (
                    [id_fallback] if id_fallback else []
                ),
                "stakes": stakes,
                "flags": {
                    "has_basic_info_block": has_basic,
                    "has_risk_evaluation": has_risk_eval,
                    "has_civil_defense": has_civil,
                    "doc_id_fallback_code": id_fallback,
                },
            },
        )
