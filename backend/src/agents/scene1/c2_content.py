"""C2 内容完整性 —— 混合检索标准条款 + 版本核查（web搜索） + LLM 比对。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.agents.base import AgentResult, BaseAgent, Finding, parse_json_response
from src.llm.provider import LLMProvider
from src.agents.llm_audit_utils import (
    C2_KEYWORDS,
    agent_result_from_llm_json,
    build_json_only_system,
    collect_chunks,
    format_snippets_for_prompt,
    retrieve_standard_snippets,
)
from src.agents.standards_seed import demo_standards_for_prompt
from src.llm import Message
from src.store.repository import Repository

if TYPE_CHECKING:
    from src.pipeline.audit import StandardCache


log = logging.getLogger(__name__)

_DIM = "C2_content_completeness"


class C2ContentAgent(BaseAgent):
    dimension = _DIM

    def __init__(
        self,
        provider: LLMProvider,
        text_model: str,
        *,
        repo: Repository | None = None,
        temperature: float = 0.0,
        standard_cache: "StandardCache | None" = None,
    ) -> None:
        super().__init__(provider, text_model, temperature=temperature)
        self.repo = repo
        self.standard_cache = standard_cache

    def run(self, chunks: list[dict[str, Any]]) -> AgentResult:
        refs = collect_chunks(
            chunks,
            keywords=C2_KEYWORDS,
            chunk_types=("TEXT", "TABLE_SUMMARY"),
        )
        excerpt = "\n---\n".join(r.excerpt for r in refs if r.excerpt.strip())
        if not excerpt.strip():
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                score=0,
                confidence=15,
                details="文档无可用文本，无法审核内容完整性。",
                need_human_review=True,
            )

        # ── 1. 混合检索标准条款（优先从缓存） ─────────────────────────────
        if self.standard_cache is not None:
            snippets = self.standard_cache.get(_DIM) or []
        else:
            snippets = []
        if not snippets:
            query = excerpt[:800]
            snippets = retrieve_standard_snippets(self.repo, _DIM, query, top_k=5)
        if not snippets:
            snippets = demo_standards_for_prompt(_DIM)

        # ── 2. 标准版本核查：提取引用编号 → web 搜索 → 获取版本上下文 ────
        version_section = ""
        cited_version_info: list[str] = []
        if self.repo:
            try:
                from src.standards_lib.normalizer import extract_citations
                from src.standards_lib.version_fetcher import (
                    fetch_all_version_contexts,
                    format_version_contexts_for_prompt,
                )
                full_text = "\n".join(c.get("content") or "" for c in chunks)
                citations = extract_citations(full_text)
                if citations:
                    contexts = fetch_all_version_contexts(citations, self.repo, max_citations=8)
                    version_section = format_version_contexts_for_prompt(contexts)
                    cited_version_info = [
                        f"{ctx.number_raw}（引用年份:{ctx.cited_year}）"
                        for ctx in contexts if ctx.cited_year
                    ]
                    log.info(
                        "C2 版本核查：找到 %d 个标准引用，%d 个有年份",
                        len(contexts), len(cited_version_info),
                    )
            except Exception as e:
                log.warning("C2 版本核查失败（非致命）: %s", e)

        # ── 3. 构建 prompt ────────────────────────────────────────────────
        system = build_json_only_system(
            "你是石油化工管道作业指导书审核专家。\n"
            "结合「标准条款摘要」「标准版本参考信息」与「文档摘录」，逐项判断以下5项内容完整性要求：\n"
            "①技术参数是否正确（关键参数如压力/温度/里程是否有明确数值，与标准要求是否一致）；\n"
            "②引用标准是否为现行有效版本（对照「标准版本参考信息」中的搜索结果判断，"
            "若搜索结果显示有更新版本而文档仍引用旧版，应标记为 finding）；\n"
            "③岗位职责是否包含安全环保责任（HSE/QHSE职责是否落实到人）；\n"
            "④作业指引描述是否准确合理（操作步骤是否清晰，风险辨识与应急处置要点是否涵盖）；\n"
            "⑤应急流程和应急处置卡是否合理（报告程序、现场处置顺序、警戒与恢复步骤）。\n"
            "每条缺失或不合规写一条 finding，②项 finding 需注明引用年份与最新年份。\n"
            "score: 12=五项全部合规，10-11=一项轻微不足，7-9=一项明显缺失，4-6=两项以上缺失，0-3=严重不符。\n\n"
            "输出格式要求：\n"
            "每个 finding 必须包含：\n"
            "- severity: high/medium/low\n"
            "- description: 问题描述\n"
            "- evidence: 原文证据\n"
            "- rule_id: 规则依据ID（如 TSG31 3.2）\n"
            "- is_problem: true（是否有问题）\n"
            "- problem_type: 问题类型（如\"缺少技术参数\"、\"标准版本过期\"等）\n"
            "- rule_basis: 规则依据原文（如\"依据《...》第X条：...\"）\n"
            "- correction_suggestion: 具体修改建议"
        )

        version_block = f"\n{version_section}\n" if version_section else ""
        user = (
            "## 标准条款摘要\n"
            f"{format_snippets_for_prompt(snippets)}\n"
            f"{version_block}"
            "## 文档摘录\n"
            + "\n".join(f"[{r.section_path}][p{r.page_start}] {r.excerpt[:500]}" for r in refs)
        )

        # ── 4. LLM 调用 ──────────────────────────────────────────────────
        try:
            raw = self.provider.call_text(
                [Message(role="system", content=system), Message(role="user", content=user)],
                model=self.text_model,
                temperature=self.temperature,
                max_tokens=1200,
            )
            data = parse_json_response(raw)
        except Exception as e:
            log.warning("C2 LLM 失败: %s", e)
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                score=0,
                confidence=20,
                details=f"LLM 调用失败：{e}",
                extra={"standard_snippet_ids": [s.get("id", s.get("clause_num")) for s in snippets]},
                need_human_review=True,
            )

        if not data:
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                score=0,
                confidence=25,
                details="LLM 未返回可解析 JSON。",
                extra={"standard_snippet_ids": [s.get("id") for s in snippets if isinstance(s, dict)]},
                need_human_review=True,
            )

        result = agent_result_from_llm_json(data, dimension=self.dimension, max_score=12)
        result.extra["retrieved_standards"] = [
            f"{s.get('standard_name', '')}-{s.get('clause_num', '')}" for s in snippets
        ]
        if cited_version_info:
            result.extra["version_checked"] = cited_version_info

        # ── 5. 补充规则层：unlisted（正文引用但未列入引用清单）────────────
        if self.repo:
            try:
                from src.standards_lib.checker import check_standard_versions, version_findings_extra
                ver_findings = [
                    vf for vf in check_standard_versions(chunks, self.repo)
                    if vf.kind == "unlisted"
                ]
                if ver_findings:
                    result.extra.update(version_findings_extra(ver_findings))
                    for vf in ver_findings:
                        d = vf.to_finding_dict()
                        result.findings.append(Finding(
                            severity=d["severity"],
                            description=d["description"],
                            evidence=d["evidence"],
                            rule_id=d["rule_id"],
                        ))
            except Exception as e:
                log.warning("C2 unlisted 核查失败（非致命）: %s", e)

        return result
