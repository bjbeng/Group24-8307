"""L2 标准遵从度（场景一先按 GB32167 延伸：正文数据/引用与完整性要求一致性）。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from src.agents.base import AgentResult, BaseAgent, parse_json_response
from src.agents.llm_audit_utils import (
    C2_KEYWORDS,
    L2_KEYWORDS,
    agent_result_from_llm_json,
    build_json_only_system,
    collect_chunks,
    format_snippets_for_prompt,
    retrieve_standard_snippets,
)
from src.agents.standards_seed import demo_standards_for_prompt
from src.llm import Message
from src.llm.provider import LLMProvider
from src.store.repository import Repository
from src.standards_lib.checker import check_standard_versions, version_findings_extra

if TYPE_CHECKING:
    from src.pipeline.audit import StandardCache


log = logging.getLogger(__name__)

_DIM = "L2_standards"


class L2StandardsAgent(BaseAgent):
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
        refs = collect_chunks(chunks, keywords=L2_KEYWORDS, chunk_types=("TEXT", "HEADING", "TABLE_SUMMARY"))
        excerpt = "\n---\n".join(r.excerpt for r in refs if r.excerpt.strip())
        if len(excerpt) < 200:
            refs2 = collect_chunks(chunks, keywords=C2_KEYWORDS, chunk_types=("TEXT", "TABLE_SUMMARY"))
            excerpt2 = "\n---\n".join(r.excerpt for r in refs2 if r.excerpt.strip())
            if excerpt2:
                excerpt = excerpt2
                refs = refs2

        if not excerpt.strip():
            refs_fallback = collect_chunks(chunks, max_chars=6000)
            excerpt = "\n".join(r.excerpt[:400] for r in refs_fallback[:15])
            refs = refs_fallback[:15]

        if not excerpt.strip():
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                score=0,
                confidence=15,
                details="无文本可审。",
                need_human_review=True,
            )

        # 优先从缓存取标准条款
        if self.standard_cache is not None:
            snippets = self.standard_cache.get(_DIM) or []
        else:
            snippets = []
        if not snippets:
            snippets = retrieve_standard_snippets(self.repo, _DIM, excerpt[:800], top_k=4)
        if not snippets:
            snippets = demo_standards_for_prompt(_DIM)

        system = build_json_only_system(
            "你是油气管道标准符合性审核员。"
            "依据 GB32167 等摘要，判断文档中出现的管道技术参数、里程、压力、引用标准版本等表述"
            "是否与摘要要求严重矛盾，或明显虚构/漏引。\n\n"
            "输出格式要求：\n"
            "每个 finding 必须包含：\n"
            "- severity: high/medium/low\n"
            "- description: 问题描述\n"
            "- evidence: 原文证据\n"
            "- rule_id: 规则依据ID（如 GB32167-5.1-e-1）\n"
            "- is_problem: true（是否有问题）\n"
            "- problem_type: 问题类型（如\"标准版本过期\"、\"技术参数不符\"等）\n"
            "- rule_basis: 规则依据原文\n"
            "- correction_suggestion: 具体修改建议"
        )
        user = (
            "## 标准摘要\n"
            f"{format_snippets_for_prompt(snippets)}\n\n"
            "## 文档摘录（带位置信息）\n"
            + "\n".join(f"[{r.section_path}][p{r.page_start}] {r.excerpt[:500]}" for r in refs)
        )
        try:
            raw = self.provider.call_text(
                [Message(role="system", content=system), Message(role="user", content=user)],
                model=self.text_model,
                temperature=self.temperature,
                max_tokens=900,
            )
            data = parse_json_response(raw)
        except Exception as e:
            log.warning("L2 LLM 失败: %s", e)
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                score=0,
                confidence=20,
                details=f"LLM 调用失败：{e}",
                need_human_review=True,
            )

        if not data:
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                score=0,
                confidence=25,
                details="LLM 未返回可解析 JSON。",
                need_human_review=True,
            )

        result = agent_result_from_llm_json(data, dimension=self.dimension, max_score=12)
        result.extra["retrieved_standards"] = [
            f"{s.get('standard_name', '')}-{s.get('clause_num', '')}" for s in snippets
        ]

        # 确定性版本核查（outdated / unlisted / untraceable）
        if self.repo:
            try:
                from src.standards_lib.checker import check_standard_versions, version_findings_extra
                from src.agents.base import Finding
                ver_findings = check_standard_versions(chunks, self.repo)
                result.extra.update(version_findings_extra(ver_findings))
                for vf in ver_findings:
                    d = vf.to_finding_dict()
                    result.findings.append(Finding(
                        severity=d["severity"],
                        description=d["description"],
                        evidence=d["evidence"],
                        rule_id=d["rule_id"],
                        is_problem=True,
                        problem_type="引用规范问题",
                        rule_basis="依据《工程建设标准编写规定》：引用的标准必须为现行有效版本",
                        correction_suggestion="核实并更新标准版本号，确保引用的是最新有效版本",
                    ))
                # 已废止标准引用 → 强制降到 partial
                if any(vf.severity == "high" for vf in ver_findings) and result.verdict == "pass":
                    result.verdict = "partial"
                    result.score = min(result.score or 12, 9)
                    result.details += "；引用了已废止标准。"
                    result.need_human_review = True
            except Exception as e:
                log.warning("L2 版本核查失败（非致命）: %s", e)

        return result
