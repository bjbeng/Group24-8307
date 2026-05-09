"""E2 应急处置 —— FTS（QSY1217/AQ3057）+ LLM 评估流程合理性与处置卡一致性。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.agents.base import AgentResult, BaseAgent, parse_json_response
from src.agents.llm_audit_utils import (
    E2_KEYWORDS,
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

if TYPE_CHECKING:
    from src.pipeline.audit import StandardCache


log = logging.getLogger(__name__)

_DIM = "E2_emergency"
_APPENDIX_HINTS = ("附录", "处置卡", "应急卡", "现场处置卡", "应急处置卡")


def _is_appendix_candidate(ref: Any) -> bool:
    section_path = str(getattr(ref, "section_path", "") or "")
    excerpt = str(getattr(ref, "excerpt", "") or "")
    if any(hint in section_path for hint in _APPENDIX_HINTS):
        return True
    upper_section = section_path.upper()
    if upper_section.startswith("APP") or upper_section.startswith("APPENDIX"):
        return True
    return any(hint in excerpt for hint in _APPENDIX_HINTS)


def _format_refs(refs: list[Any], *, limit: int = 6) -> str:
    if not refs:
        return "（无）"
    return "\n".join(
        f"[{ref.section_path}][p{ref.page_start}] {ref.excerpt[:400]}" for ref in refs[:limit]
    )


def _normalize_steps(raw_steps: Any) -> list[str]:
    if not isinstance(raw_steps, list):
        return []
    steps: list[str] = []
    for item in raw_steps:
        text = str(item).strip()
        if text:
            steps.append(text)
    return steps


class E2EmergencyAgent(BaseAgent):
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
            keywords=E2_KEYWORDS,
            chunk_types=("TEXT", "TABLE_SUMMARY"),
        )
        excerpt = "\n---\n".join(r.excerpt for r in refs if r.excerpt.strip())
        if not excerpt.strip() or not any(kw in excerpt for kw in E2_KEYWORDS):
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                score=0,
                confidence=20,
                details="未在文档摘录中找到应急处置相关关键词（应急/处置/事故等）。",
                need_human_review=True,
            )

        snippets = self._load_standard_snippets(excerpt)
        step_data = self._extract_step_alignment(refs)
        if not step_data:
            return self._run_semantic_review(refs, snippets, None)
        return self._run_semantic_review(refs, snippets, step_data)

    def _load_standard_snippets(self, excerpt: str) -> list[dict[str, Any]]:
        if self.standard_cache is not None:
            snippets = self.standard_cache.get(_DIM) or []
        else:
            snippets = []
        if not snippets:
            snippets = retrieve_standard_snippets(self.repo, _DIM, excerpt[:800], top_k=5)
        if not snippets:
            snippets = demo_standards_for_prompt(_DIM)
        return snippets

    def _extract_step_alignment(self, refs: list[Any]) -> dict[str, Any] | None:
        main_refs = [ref for ref in refs if not _is_appendix_candidate(ref)]
        appendix_refs = [ref for ref in refs if _is_appendix_candidate(ref)]
        missing_side = "none"
        if not main_refs and not appendix_refs:
            missing_side = "both"
        elif not main_refs:
            missing_side = "main"
        elif not appendix_refs:
            missing_side = "appendix"

        if missing_side == "both":
            return {
                "main_steps": [],
                "appendix_steps": [],
                "missing_side": "both",
                "summary": "未找到可用于抽取步骤的正文或附录/处置卡段落。",
            }

        system = (
            "你是应急处置步骤抽取助手。"
            "请分别从正文应急描述与附录/处置卡描述中抽取关键步骤，"
            "每一步保持短句，不要编造。"
            "只输出 JSON："
            '{"main_steps":["步骤1"],"appendix_steps":["步骤1"],'
            '"missing_side":"main|appendix|both|none","summary":"一句话"}'
        )
        user = (
            "## 正文应急候选段落\n"
            f"{_format_refs(main_refs)}\n\n"
            "## 附录/处置卡候选段落\n"
            f"{_format_refs(appendix_refs)}\n\n"
            f"已知缺失侧：{missing_side}"
        )
        try:
            raw = self.provider.call_text(
                [Message(role="system", content=system), Message(role="user", content=user)],
                model=self.text_model,
                temperature=0.0,
                max_tokens=700,
            )
            data = parse_json_response(raw)
        except Exception as e:
            log.warning("E2 步骤抽取失败: %s", e)
            return None

        if not data:
            return None

        main_steps = _normalize_steps(data.get("main_steps"))
        appendix_steps = _normalize_steps(data.get("appendix_steps"))
        resolved_missing = str(data.get("missing_side") or missing_side).lower()
        if resolved_missing not in {"main", "appendix", "both", "none"}:
            resolved_missing = missing_side
        return {
            "main_steps": main_steps,
            "appendix_steps": appendix_steps,
            "missing_side": resolved_missing,
            "summary": str(data.get("summary") or ""),
        }

    def _run_semantic_review(
        self,
        refs: list[Any],
        snippets: list[dict[str, Any]],
        step_data: dict[str, Any] | None,
    ) -> AgentResult:
        system = build_json_only_system(
            "你是应急管理与油气管道安全专家。"
            "根据标准条款，判断文档中的应急处置流程、报告与现场处置顺序是否合理，"
            "是否与『先控源、防扩大、有序疏散抢险』等原则严重冲突。"
            "如果给出了正文步骤和附录/处置卡步骤，必须重点检查两者是否缺项、倒序或矛盾。"
            "若仅细节不清标 partial；明显违背标 fail；信息不足标 uncertain。\n\n"
            "输出格式要求：\n"
            "每个 finding 必须包含：\n"
            "- severity: high/medium/low\n"
            "- description: 问题描述\n"
            "- evidence: 原文证据\n"
            "- rule_id: 规则依据ID（如 QSY1217 6.1）\n"
            "- is_problem: true（是否有问题）\n"
            "- problem_type: 问题类型（如\"应急流程缺失\"、\"处置顺序不合理\"、\"正文与处置卡不一致\"等）\n"
            "- rule_basis: 规则依据原文（如\"依据《油气管道线路完整性管理规范》第6.1条：...\"）\n"
            "- correction_suggestion: 具体修改建议"
        )
        step_block = ""
        if step_data is not None:
            step_block = (
                "\n\n## 正文/附录步骤抽取结果\n"
                f"missing_side={step_data.get('missing_side', 'none')}\n"
                f"summary={step_data.get('summary', '')}\n"
                f"main_steps={step_data.get('main_steps', [])}\n"
                f"appendix_steps={step_data.get('appendix_steps', [])}"
            )
        user = (
            "## 相关标准摘要\n"
            f"{format_snippets_for_prompt(snippets)}\n\n"
            "## 文档应急相关摘录（带位置信息）\n"
            + "\n".join(f"[{r.section_path}][p{r.page_start}] {r.excerpt[:500]}" for r in refs)
            + step_block
        )
        try:
            raw = self.provider.call_text(
                [Message(role="system", content=system), Message(role="user", content=user)],
                model=self.text_model,
                temperature=self.temperature,
                max_tokens=1024,
            )
            data = parse_json_response(raw)
        except Exception as e:
            log.warning("E2 LLM 失败: %s", e)
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
        result.extra = {
            **result.extra,
            "retrieved_standards": [
                f"{s.get('standard_name', '')}-{s.get('clause_num', '')}" for s in snippets
            ],
            "main_steps": step_data.get("main_steps", []) if step_data else [],
            "appendix_steps": step_data.get("appendix_steps", []) if step_data else [],
            "step_alignment_summary": step_data.get("summary", "") if step_data else "",
            "missing_side": step_data.get("missing_side", "none") if step_data else "none",
        }
        return result
