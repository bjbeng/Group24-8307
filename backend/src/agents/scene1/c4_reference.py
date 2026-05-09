"""C4 引用文件可追溯性 —— LLM + 外部知识三层混合架构。

赛题原文要求：
- 附件以及涉及到的相关标准是否真实存在，是否为有效文件
- 文档里"详见附录 X"、"参见表 N"、"按 GBxxxx" 这类引用必须有可追溯目标

三层架构：
  Layer 1 正则抽取（保留现有 extract_references）
  Layer 2 Enrichment（YAML + SQLite + DuckDuckGo 查真实性/有效性）
  Layer 3 LLM 推理（C3 风格批量并行，评判语义可追溯性）
  Layer 2 确定性 findings 附加（outdated / unlisted / untraceable）
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.agents.base import AgentResult, BaseAgent, Finding, parse_json_response
from src.agents.llm_audit_utils import (
    ChunkRef,
    agent_result_from_llm_json,
    build_json_only_system,
    collect_chunks_all,
    format_snippets_for_prompt,
    retrieve_standard_snippets,
)
from src.agents.standards_seed import demo_standards_for_prompt
from src.llm import Message
from src.llm.provider import LLMProvider
from src.standards_lib.checker import (
    VersionFinding,
    check_standard_versions,
    version_findings_extra,
)
from src.standards_lib.normalizer import Citation, extract_citations
from src.standards_lib.version_fetcher import (
    VersionContext,
    fetch_version_context,
    format_version_contexts_for_prompt,
)
from src.store.repository import Repository

if TYPE_CHECKING:
    from src.pipeline.audit import StandardCache


log = logging.getLogger(__name__)

_DIM = "C4_reference"

_BATCH_CHUNK_SIZE = 10
_MAX_CONCURRENT_LLM_CALLS = 8

# 每个 batch 最多多少字符（控制 LLM context）
_BATCH_CHAR_LIMIT = 4500


# ---------------------------------------------------------------------------
# 引用模式（保留旧的，也支持 extract_citations 的新正则）
# ---------------------------------------------------------------------------

APPENDIX_REF_RE = re.compile(
    r"(?:详见|参见|参考|见|按|依据)?\s*附\s*录\s*([A-Z]|[一二三四五六七八九十])",
    re.IGNORECASE,
)

TABLE_REF_RE = re.compile(
    r"(?:详见|参见|参考|见|如)?\s*表\s*(\d+(?:[-.]\d+)?)\s*(?:所示|中|：)?",
)

FIGURE_REF_RE = re.compile(
    r"(?:详见|参见|参考|见|如)?\s*图\s*(\d+(?:[-.]\d+)?)\s*(?:所示|：)?",
)

APPENDIX_ANCHOR_RE = re.compile(
    r"^[\s\-]*附\s*录\s*([A-Z]|[一二三四五六七八九十])(?:\s|[:：]|$)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class ReferenceFacts:
    appendix_refs: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    table_refs: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    figure_refs: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    standard_refs: list[dict[str, Any]] = field(default_factory=list)

    appendix_anchors: set[str] = field(default_factory=set)
    section_refs: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))


@dataclass
class ValidatedCitation:
    raw: str
    number_normalized: str
    cited_year: int | None
    exists: bool
    latest_year: int | None
    status: str
    superseded_by: str | None
    web_snippets: list[str]
    from_cache: bool
    evidence: str


# ---------------------------------------------------------------------------
# Layer 1：引用抽取（保留现有正则逻辑）
# ---------------------------------------------------------------------------


def extract_references(chunks: list[dict[str, Any]]) -> ReferenceFacts:
    facts = ReferenceFacts()
    facts.appendix_refs = defaultdict(list)
    facts.table_refs = defaultdict(list)
    facts.figure_refs = defaultdict(list)

    for c in chunks:
        chunk_id = c.get("chunk_id", "")
        section_path = c.get("section_path", "")
        title = (c.get("title") or "")
        content = c.get("content") or ""
        chunk_type = c.get("chunk_type", "")
        text = f"{title}\n{content}"

        if section_path:
            facts.section_refs[section_path].append(chunk_id)

        if chunk_type == "heading" or chunk_type == "HEADING":
            m = APPENDIX_ANCHOR_RE.match(title)
            if m:
                facts.appendix_anchors.add(m.group(1).upper())

        for m in APPENDIX_REF_RE.finditer(text):
            tag = m.group(1).upper()
            facts.appendix_refs[tag].append(chunk_id)
        for m in TABLE_REF_RE.finditer(text):
            facts.table_refs[m.group(1)].append(chunk_id)
        for m in FIGURE_REF_RE.finditer(text):
            facts.figure_refs[m.group(1)].append(chunk_id)

        for m in _STANDARD_REF_RE.finditer(text):
            family_raw = m.group(1).upper().replace(" ", "").replace("/", "")
            if family_raw == "GBT":
                family = "GBT"
            else:
                family = family_raw
            facts.standard_refs.append(
                {
                    "raw": m.group(0).strip(),
                    "family": family,
                    "number": m.group(2),
                    "year": m.group(3),
                    "chunk_id": chunk_id,
                }
            )

    return facts


_STANDARD_REF_RE = re.compile(
    r"\b("
    r"GB(?:\s*/\s*T)?|GBT|"
    r"QSY|"
    r"AQ|"
    r"TSG|"
    r"SY|"
    r"JB|"
    r"NB"
    r")\s*(\d+(?:\.\d+)*)"
    r"(?:\s*[-—]\s*(\d{4}))?",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Layer 2： Enrichment（确定性）
# ---------------------------------------------------------------------------


def _enrich_standard_refs(
    standard_refs: list[dict[str, Any]],
    repo: Repository | None,
) -> list[ValidatedCitation]:
    """对每个标准引用做存在性/有效性验证，产出 ValidatedCitation。"""
    results: list[ValidatedCitation] = []
    seen: set[str] = set()

    for ref in standard_refs:
        raw = ref.get("raw", "")
        norm = _normalize_standard_ref(raw)
        if not norm or norm in seen:
            continue
        seen.add(norm)

        citation = Citation(
            number_raw=raw,
            number_normalized=norm,
            year=int(ref["year"]) if ref.get("year") else None,
            context="",
        )

        exists = False
        latest_year: int | None = None
        status = "unknown"
        superseded_by: str | None = None
        web_snippets: list[str] = []
        from_cache = False

        if repo:
            row = repo.get_standard_version(norm)
            if row:
                exists = True
                latest_year = row.get("latest_year")
                status = row.get("status", "current")
                superseded_by = row.get("superseded_by")
                snippets_raw = row.get("search_snippets") or []
                if isinstance(snippets_raw, str):
                    try:
                        import json
                        snippets_raw = json.loads(snippets_raw)
                    except Exception:
                        snippets_raw = []
                web_snippets = snippets_raw or []
                from_cache = True

        # DuckDuckGo 兜底（当本地库不存在时）
        if not exists and repo:
            try:
                ctx = fetch_version_context(citation, repo)
                exists = bool(ctx.snippets)
                web_snippets = ctx.snippets
                from_cache = ctx.from_cache
                row2 = repo.get_standard_version(norm)
                if row2:
                    latest_year = row2.get("latest_year")
                    status = row2.get("status", "unknown")
                    superseded_by = row2.get("superseded_by")
            except Exception as e:
                log.warning("fetch_version_context 失败（%s）: %s", norm, e)

        results.append(ValidatedCitation(
            raw=raw,
            number_normalized=norm,
            cited_year=citation.year,
            exists=exists,
            latest_year=latest_year,
            status=status,
            superseded_by=superseded_by,
            web_snippets=web_snippets,
            from_cache=from_cache,
            evidence=f"标准引用：{raw}",
        ))

    return results


def _normalize_standard_ref(raw: str) -> str:
    """将标准引用原始字符串规范化为无年份的 key。"""
    import re as _re
    # 去掉年份后缀
    no_year = _re.sub(r"[—\-](?:19|20)\d{2}$", "", raw.strip()).strip()
    # 统一空格
    no_year = _re.sub(r"\s+", "", no_year).upper()
    # 简单 family 映射
    family_map = {
        "GB/T": "GBT", "GBT": "GBT", "GB": "GB",
        "Q/SY": "QSY", "QSY": "QSY",
        "TSG": "TSG", "AQ": "AQ",
        "SY/T": "SYT", "SY": "SY",
        "JB": "JB", "NB/T": "NBT",
    }
    for pat, norm in sorted(family_map.items(), key=lambda x: -len(x[0])):
        m = _re.match(_re.escape(pat), no_year, _re.IGNORECASE)
        if m:
            rest = no_year[m.end():].replace(".", "")
            return norm + rest
    return no_year


# ---------------------------------------------------------------------------
# LLM batch 辅助
# ---------------------------------------------------------------------------


def _split_into_batches(refs: list[ChunkRef]) -> list[list[ChunkRef]]:
    batches: list[list[ChunkRef]] = []
    for i in range(0, len(refs), _BATCH_CHUNK_SIZE):
        batches.append(refs[i : i + _BATCH_CHUNK_SIZE])
    return batches


def _format_reference_summary(facts: ReferenceFacts) -> str:
    """生成四类引用的汇总表供 LLM 参考。"""
    lines = ["## 文档引用汇总\n"]

    lines.append("### 附录引用")
    if facts.appendix_refs:
        for tag, chunks in facts.appendix_refs.items():
            defined = "✓" if tag in facts.appendix_anchors else "✗"
            lines.append(f"- 附录 {tag}：正文中出现 {len(chunks)} 次 [{defined} 已定义]")
    else:
        lines.append("（无）")

    lines.append("\n### 标准引用")
    if facts.standard_refs:
        seen = []
        for ref in facts.standard_refs:
            key = ref["raw"]
            if key not in seen:
                seen.append(key)
                lines.append(f"- {key}")
        lines.append(f"\n（共计 {len(seen)} 个不同标准号）")
    else:
        lines.append("（无）")

    lines.append(f"\n### 表格引用：{sum(len(v) for v in facts.table_refs.values())} 处")
    lines.append(f"### 图片引用：{sum(len(v) for v in facts.figure_refs.values())} 处")

    return "\n".join(lines)


def _build_batch_prompt(
    batch_refs: list[ChunkRef],
    snippets: list[dict[str, Any]],
    ref_summary: str,
    validated: list[ValidatedCitation],
    version_ctx_str: str,
) -> tuple[str, str]:
    """构建单个 batch 的 system + user prompt。"""
    parts: list[str] = []
    for ref in batch_refs:
        header = (
            f"[chunk_id={ref.chunk_id} | section_path={ref.section_path} | "
            f"page={ref.page_start} | anchor={ref.anchor_text[:20] if ref.anchor_text else ''}]"
        )
        parts.append(f"{header}\n{ref.excerpt}")
    sampled = "\n---\n".join(parts)

    system = build_json_only_system(
        "你是中文工业文档审校编辑，负责核查引用文件可追溯性。"
        "任务：检查文档中引用的附录、表格、图片、标准是否可被追溯到真实存在且有效的目标。"
        "评分规则：\n"
        "1. 引用了不存在的附录/表格/图片 → high\n"
        "2. 标准编号在库中不存在且无网络证据 → high\n"
        "3. 引用了已被废止/替代的标准 → medium\n"
        "4. 正文引用了某标准但未列入引用清单章节 → medium\n"
        "5. 标准编号缺少年份（无法追溯版本）→ low\n"
        "6. 定义了附录但从未被引用 → low（仅警告）\n\n"
        "输出格式要求：\n"
        "每个 finding 必须包含：\n"
        "- severity: high/medium/low\n"
        "- description: 问题描述\n"
        "- evidence: 原文证据\n"
        "- rule_id: 规则依据ID（如 C4.appendix_missing）\n"
        "- is_problem: true/false\n"
        "- problem_type: 问题类型（引用不存在/标准无效/版本缺失/无引用等）\n"
        "- rule_basis: 规则依据\n"
        "- correction_suggestion: 修改建议\n"
        "- chunk_id: 出问题的 chunk_id\n"
        "- section_path: chunk 所属章节路径\n"
        "- page_number: 所在页码\n"
        "- anchor_text: 锚文本片段"
    )

    user = (
        "## GBT1.1 引用规范摘要\n"
        f"{format_snippets_for_prompt(snippets)}\n\n"
        "## 文档引用汇总\n"
        f"{ref_summary}\n\n"
        "## 标准验证结果\n"
        f"{version_ctx_str}\n\n"
        "## 文档段落（本次batch）\n"
        f"{sampled}\n"
    )
    return system, user


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class C4ReferenceAgent(BaseAgent):
    dimension = _DIM

    def __init__(
        self,
        provider: LLMProvider,
        text_model: str,
        *,
        repo: Repository | None = None,
        temperature: float = 0.0,
        standard_cache: "StandardCache | None" = None,
        max_concurrent_llm: int = _MAX_CONCURRENT_LLM_CALLS,
    ) -> None:
        super().__init__(provider, text_model, temperature=temperature)
        self.repo = repo
        self.standard_cache = standard_cache
        self.max_concurrent_llm = max_concurrent_llm

    def run(self, chunks: list[dict[str, Any]]) -> AgentResult:
        # Layer 1：正则抽取四类引用
        facts = extract_references(chunks)

        # Layer 2 确定性 pre-check（outdated/unlisted/untraceable）
        rule_findings: list[VersionFinding] = []
        if self.repo:
            try:
                rule_findings = check_standard_versions(chunks, self.repo)
            except Exception as e:
                log.warning("check_standard_versions 失败: %s", e)

        # Layer 2 enrichment：标准引用真实性/有效性验证
        validated = _enrich_standard_refs(facts.standard_refs, self.repo)
        version_ctx_str = self._format_validated_citations(validated)

        # 全量文本块（C3 风格）
        all_refs = collect_chunks_all(chunks, chunk_types=("TEXT", "HEADING"), seed=42)
        if not all_refs:
            return self._build_result(
                facts=facts,
                rule_findings=rule_findings,
                validated=validated,
                llm_findings=[],
                llm_errors=[],
                batch_count=0,
                total_batches=0,
            )

        batches = _split_into_batches(all_refs)
        ref_map: dict[str, ChunkRef] = {r.chunk_id: r for r in all_refs}

        # 标准条款（用于 prompt）
        if self.standard_cache is not None:
            snippets = self.standard_cache.get(_DIM) or []
        else:
            snippets = []
        if not snippets:
            sample_text = " ".join(r.excerpt[:100] for r in all_refs[:5])
            snippets = retrieve_standard_snippets(self.repo, _DIM, sample_text[:600], top_k=4)
        if not snippets:
            snippets = demo_standards_for_prompt(_DIM)

        ref_summary = _format_reference_summary(facts)

        # 并发 LLM 调用
        llm_findings: list = []
        llm_errors: list[str] = []
        batch_count = 0

        max_workers = min(self.max_concurrent_llm, len(batches))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    self._run_batch, batch, snippets, ref_summary, validated, version_ctx_str, batch_idx
                ): idx
                for idx, batch in enumerate(batches)
            }
            for future in as_completed(futures):
                batch_idx = futures[future]
                try:
                    batch_findings, batch_error = future.result()
                    llm_findings.extend(batch_findings)
                    if batch_error:
                        llm_errors.append(batch_error)
                    batch_count += 1
                except Exception as e:
                    log.warning("C4 batch %d 执行异常: %s", batch_idx, e)
                    llm_errors.append(str(e))

        return self._build_result(
            facts=facts,
            rule_findings=rule_findings,
            validated=validated,
            llm_findings=llm_findings,
            llm_errors=llm_errors,
            batch_count=batch_count,
            total_batches=len(batches),
        )

    def _run_batch(
        self,
        batch: list[ChunkRef],
        snippets: list[dict[str, Any]],
        ref_summary: str,
        validated: list[ValidatedCitation],
        version_ctx_str: str,
        batch_idx: int,
    ) -> tuple[list, str | None]:
        system, user = _build_batch_prompt(
            batch, snippets, ref_summary, validated, version_ctx_str
        )
        try:
            raw = self.provider.call_text(
                [Message(role="system", content=system), Message(role="user", content=user)],
                model=self.text_model,
                temperature=self.temperature,
                max_tokens=1200,
            )
            data = parse_json_response(raw)
        except Exception as e:
            log.warning("C4 batch %d LLM 失败: %s", batch_idx, e)
            return [], str(e)

        if not data:
            return [], "LLM 返回空"

        result = agent_result_from_llm_json(data, dimension=self.dimension, max_score=12)
        return result.findings, None

    def _build_result(
        self,
        facts: ReferenceFacts,
        rule_findings: list[VersionFinding],
        validated: list[ValidatedCitation],
        llm_findings: list,
        llm_errors: list[str],
        batch_count: int,
        total_batches: int,
    ) -> AgentResult:
        # 转换 rule findings → Finding
        from src.agents.base import Finding as BaseFinding

        deterministic_findings: list[BaseFinding] = []
        for rf in rule_findings:
            fd = rf.to_finding_dict()
            deterministic_findings.append(BaseFinding(
                severity=fd["severity"],
                description=fd["description"],
                evidence=fd["evidence"],
                rule_id=fd["rule_id"],
                chunk_id=None,
                section_path="",
                anchor_text="",
                category="content",
                is_problem=True,
                problem_type=f"标准{rf.kind}",
                rule_basis="依据 standards_lib 规则库",
                correction_suggestion=f"请核实 {rf.number_raw} 的最新版本状态",
            ))

        all_findings = list(llm_findings) + deterministic_findings

        # 汇总 verdict
        verdict, score, confidence = self._derive_from_findings(all_findings)

        return AgentResult(
            dimension=self.dimension,
            verdict=verdict,
            score=score,
            confidence=confidence,
            findings=all_findings,
            details=self._build_details(facts, validated, llm_findings, deterministic_findings, llm_errors),
            extra={
                "reference_analysis": {
                    "appendix_refs": {k: len(v) for k, v in facts.appendix_refs.items()},
                    "appendix_anchors": sorted(facts.appendix_anchors),
                    "table_refs_count": sum(len(v) for v in facts.table_refs.values()),
                    "figure_refs_count": sum(len(v) for v in facts.figure_refs.values()),
                    "standards": [v.raw for v in validated],
                    "validated_standards": [
                        {
                            "raw": v.raw,
                            "exists": v.exists,
                            "status": v.status,
                            "cited_year": v.cited_year,
                            "latest_year": v.latest_year,
                        }
                        for v in validated
                    ],
                },
                "version_check": version_findings_extra(rule_findings),
                "llm_batches": {
                    "total": total_batches,
                    "succeeded": batch_count - len(llm_errors),
                },
            },
            need_human_review=(
                verdict in ("uncertain", "fail")
                or len(llm_errors) > total_batches // 2
                or (self.repo is None)
            ),
        )

    @staticmethod
    def _derive_from_findings(findings: list) -> tuple[str, int, int]:
        if not findings:
            return "pass", 12, 95

        high = sum(1 for f in findings if getattr(f, "severity", None) == "high")
        medium = sum(1 for f in findings if getattr(f, "severity", None) == "medium")
        low = sum(1 for f in findings if getattr(f, "severity", None) == "low")

        if high > 0:
            return "fail", 4, 90
        if medium > 0:
            conf = min(90, 75 + medium * 2)
            return "partial", 8, conf
        if low > 0:
            conf = min(85, 80 - low)
            return "partial", 10, conf
        return "pass", 12, 95

    @staticmethod
    def _build_details(
        facts: ReferenceFacts,
        validated: list[ValidatedCitation],
        llm_findings: list,
        deterministic_findings: list,
        llm_errors: list[str],
    ) -> str:
        exists = sum(1 for v in validated if v.exists)
        missing = len(validated) - exists
        return (
            f"附录引用 {len(facts.appendix_refs)} 个，附录定义 {len(facts.appendix_anchors)} 个，"
            f"标准引用 {len(validated)} 个（验证存在 {exists} 个，缺失 {missing} 个），"
            f"LLM 发现问题 {len(llm_findings)} 条，确定性问题 {len(deterministic_findings)} 条"
            + (f"；LLM 批处理异常: {'; '.join(llm_errors[:2])}" if llm_errors else "")
        )

    @staticmethod
    def _format_validated_citations(validated: list[ValidatedCitation]) -> str:
        if not validated:
            return "（无标准引用可验证）"
        lines = ["## 标准引用验证结果\n"]
        for v in validated:
            status_icon = "✓" if v.exists else "✗"
            year_info = f"（引用年份：{v.cited_year}，最新：{v.latest_year}）" if v.cited_year or v.latest_year else ""
            status_info = f"状态：{v.status}" + (f" → 被 {v.superseded_by} 替代" if v.superseded_by else "")
            lines.append(
                f"- {v.raw} {status_icon} {year_info} {status_info}"
            )
            if v.web_snippets:
                for s in v.web_snippets[:2]:
                    lines.append(f"  证据：{s[:100]}")
        return "\n".join(lines)