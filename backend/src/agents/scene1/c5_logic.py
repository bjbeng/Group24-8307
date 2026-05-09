"""C5 业务逻辑 —— LangGraph 编排：Explorer A（偏高温度）+ Explorer B（0 温度）+ 条件 Critic。

Explorer A/B 输出同构 JSON（verdict_hint / contradictions）；若矛盾列表与
verdict_hint 一致则跳过 Critic，直接以 B 的精确结果合并为最终 verdict。
"""

from __future__ import annotations

import json
import logging
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from src.agents.base import AgentResult, BaseAgent, parse_json_response
from src.agents.llm_audit_utils import (
    C5_KEYWORDS,
    agent_result_from_llm_json,
    collect_chunks,
    format_snippets_for_prompt,
    retrieve_standard_snippets,
)
from src.agents.standards_seed import demo_standards_for_prompt
from src.llm import Message
from src.llm.provider import LLMProvider
from src.store.repository import Repository


log = logging.getLogger(__name__)

_DIM = "C5_logic"


class C5GraphState(TypedDict, total=False):
    excerpt: str
    standard_context: str
    explorer_a: dict[str, Any]
    explorer_b: dict[str, Any]
    critic: dict[str, Any]


def _norm_contradictions(d: dict[str, Any]) -> str:
    items = d.get("contradictions") or []
    if not isinstance(items, list):
        return "[]"
    try:
        normalized = [json.dumps(x, ensure_ascii=False, sort_keys=True) for x in items]
        normalized.sort()
        return json.dumps(normalized, ensure_ascii=False)
    except (TypeError, ValueError):
        return "[]"


def explorers_agree(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if not a or not b:
        return False
    if _norm_contradictions(a) != _norm_contradictions(b):
        return False
    ha = str(a.get("verdict_hint", "")).lower()
    hb = str(b.get("verdict_hint", "")).lower()
    return ha == hb and ha in ("pass", "partial", "fail", "uncertain")


def merge_explorer_b_to_final(b: dict[str, Any]) -> dict[str, Any]:
    """A/B 一致时以 B 为准，映射为 agent_result_from_llm_json 输入。"""
    vh = str(b.get("verdict_hint", "uncertain")).lower()
    if vh not in ("pass", "partial", "fail", "uncertain"):
        vh = "partial"
    try:
        sh = int(b.get("score_hint", 8))
    except (TypeError, ValueError):
        sh = 8
    try:
        conf = int(b.get("confidence_hint", 85))
    except (TypeError, ValueError):
        conf = 85

    findings: list[dict[str, Any]] = []
    for i, c in enumerate(b.get("contradictions") or []):
        if not isinstance(c, dict):
            continue
        findings.append(
            {
                "severity": str(c.get("severity", "medium")),
                "description": str(c.get("description", ""))[:800],
                "evidence": f"{c.get('quote_a', '')} | {c.get('quote_b', '')}"[:600],
                "rule_id": str(c.get("id") or f"C5.c{i}"),
            }
        )

    return {
        "verdict": vh,
        "score": max(0, min(12, sh)),
        "confidence": max(0, min(100, conf)),
        "details": str(b.get("summary", b.get("notes", "Explorer A/B 结论一致"))),
        "findings": findings,
        "extra": {"path": "ab_merge", "notes": b.get("notes", "")},
    }


class C5LogicAgent(BaseAgent):
    dimension = _DIM

    def __init__(
        self,
        provider: LLMProvider,
        text_model: str,
        *,
        repo: Repository | None = None,
        explorer_a_temperature: float = 0.2,
        temperature: float = 0.0,
    ) -> None:
        super().__init__(provider, text_model, temperature=temperature)
        self.repo = repo
        self._explorer_a_temp = explorer_a_temperature

    def run(self, chunks: list[dict[str, Any]]) -> AgentResult:
        refs = collect_chunks(chunks, keywords=C5_KEYWORDS, chunk_types=("TEXT", "HEADING"), max_chars=6500)
        excerpt = "\n---\n".join(r.excerpt for r in refs if r.excerpt.strip())
        if not excerpt.strip():
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                score=0,
                confidence=15,
                details="无足够文本用于业务逻辑审核。",
                need_human_review=True,
            )

        rows = retrieve_standard_snippets(self.repo, _DIM, excerpt[:800], top_k=3)
        if not rows:
            rows = demo_standards_for_prompt(_DIM)
        std_block = format_snippets_for_prompt(rows)

        graph = self._compile_graph()
        try:
            state = graph.invoke(
                {
                    "excerpt": excerpt,
                    "standard_context": std_block,
                }
            )
        except Exception as e:
            log.exception("C5 LangGraph 执行失败")
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                score=0,
                confidence=15,
                details=f"C5 图执行异常：{e}",
                need_human_review=True,
            )

        critic = state.get("critic")
        if critic:
            data = critic
            path = "critic"
        else:
            data = merge_explorer_b_to_final(state.get("explorer_b") or {})
            path = "ab_merge"

        result = agent_result_from_llm_json(
            data,
            dimension=self.dimension,
            max_score=12,
            default_details=str(data.get("details", "")),
        )
        ex = dict(result.extra) if result.extra else {}
        ex["langgraph_path"] = path
        ex["retrieved_standards"] = [
            f"{r.get('standard_name', '')}-{r.get('clause_num', '')}" for r in rows
        ]
        result.extra = ex
        return result

    def _explorer_prompt_tail(self) -> str:
        return (
            "识别**前后矛盾**：同一实体不同数字、步骤顺序冲突、时间与附件/报表不符、"
            "禁止条款与操作描述冲突等。\n"
            "只输出 JSON：\n"
            '{"verdict_hint":"pass|partial|fail|uncertain",'
            '"score_hint":0-12,"confidence_hint":0-100,'
            '"summary":"一句话",'
            '"contradictions":['
            '{"id":"c1","severity":"high|medium|low","description":"",'
            '"quote_a":"","quote_b":"",'
            '"is_problem":true,"problem_type":"逻辑矛盾","rule_basis":"","correction_suggestion":""}],'
            '"notes":""}\n'
            "无矛盾时 contradictions 为 []。\n"
            "每个 contradiction 必须包含：is_problem=true, problem_type（如\"数据不一致\"、\"步骤冲突\"等）"
        )

    def _call_explorer(self, excerpt: str, std: str, *, temperature: float) -> dict[str, Any]:
        role = (
            "【Explorer A — 高召回】宁可多报疑点，后续会仲裁。\n"
            if temperature > 0.05
            else "【Explorer B — 高精度】仅报告证据充分的矛盾。\n"
        )
        system = role + self._explorer_prompt_tail() + "\n可参考标准摘要，但以文档摘录为主。"
        user = f"## 标准摘要\n{std}\n\n## 文档摘录\n{excerpt[:6000]}\n"
        raw = self.provider.call_text(
            [Message(role="system", content=system), Message(role="user", content=user)],
            model=self.text_model,
            temperature=temperature,
            max_tokens=1200,
        )
        return parse_json_response(raw) or {}

    def _call_critic(self, excerpt: str, std: str, a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
        system = (
            "你是仲裁审核员。下面两份 JSON 为两名审核员对同一文档的矛盾分析（Explorer A / B）。"
            "裁决哪些矛盾成立；输出最终 JSON：\n"
            '{"verdict":"pass|partial|fail|uncertain","score":0-12,"confidence":0-100,'
            '"details":"摘要","findings":[{"severity":"high|medium|low","description":"",'
            '"evidence":"","rule_id":"","is_problem":true,"problem_type":"逻辑矛盾",'
            '"rule_basis":"","correction_suggestion":""}],"extra":{}}\n'
            "只输出 JSON，不要围栏。\n"
            "每个 finding 必须包含：is_problem, problem_type（如\"数据不一致\"、\"步骤冲突\"等）, rule_basis, correction_suggestion"
        )
        payload = {
            "explorer_a": a,
            "explorer_b": b,
        }
        user = (
            f"## 标准摘要\n{std}\n\n## 文档摘录（前段）\n{excerpt[:3500]}\n\n"
            f"## 双方结论\n{json.dumps(payload, ensure_ascii=False)[:7000]}\n"
        )
        raw = self.provider.call_text(
            [Message(role="system", content=system), Message(role="user", content=user)],
            model=self.text_model,
            temperature=0.0,
            max_tokens=1400,
        )
        return parse_json_response(raw) or {}

    def _compile_graph(self) -> Any:
        def node_explorer_a(state: C5GraphState) -> dict[str, Any]:
            out = self._call_explorer(
                state["excerpt"],
                state["standard_context"],
                temperature=self._explorer_a_temp,
            )
            return {"explorer_a": out}

        def node_explorer_b(state: C5GraphState) -> dict[str, Any]:
            out = self._call_explorer(
                state["excerpt"],
                state["standard_context"],
                temperature=0.0,
            )
            return {"explorer_b": out}

        def route_after_b(state: C5GraphState) -> str:
            if explorers_agree(state.get("explorer_a") or {}, state.get("explorer_b") or {}):
                return "done"
            return "critic"

        def node_critic(state: C5GraphState) -> dict[str, Any]:
            out = self._call_critic(
                state["excerpt"],
                state["standard_context"],
                state.get("explorer_a") or {},
                state.get("explorer_b") or {},
            )
            return {"critic": out}

        g = StateGraph(C5GraphState)
        g.add_node("explorer_a", node_explorer_a)
        g.add_node("explorer_b", node_explorer_b)
        g.add_node("critic", node_critic)
        g.add_edge(START, "explorer_a")
        g.add_edge("explorer_a", "explorer_b")
        g.add_conditional_edges(
            "explorer_b",
            route_after_b,
            {"done": END, "critic": "critic"},
        )
        g.add_edge("critic", END)
        return g.compile()
