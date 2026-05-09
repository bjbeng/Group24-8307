"""DimSupervisor：单维度 2+1 审核主管。

LangGraph 状态机：
  START → build_context → explorer_a → explorer_b → critic → END

Explorer A（高召回）和 Explorer B（高精度）独立地对同一维度做完全相同的审核任务，
Critic 拿到 A+B 的全部输出后验证证据、选择/合并最优内容，产出最终 AgentResult。

对于客观维度（OBJECTIVE_DIMENSIONS），跳过 Explorer A，只跑 B + 轻量 Critic。
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from src.agents.base import AgentResult, Finding, parse_json_response
from src.harness.agent_group.roles import (
    DIMENSION_CHECKPOINTS,
    LLM_2PLUS1_DIMENSIONS,
    OBJECTIVE_DIMENSIONS,
    build_critic_system,
    build_critic_user_prompt,
    build_explorer_system,
    build_explorer_user_prompt,
)
from src.harness.guardrails.human_review import should_human_review
from src.harness.guardrails.retry_policy import AgentCallPolicy, with_retry
from src.harness.guardrails.schemas import (
    parse_critic_output,
    parse_explorer_output,
)
from src.harness.hooks.registry import get_global_registry
from src.harness.memory.context_builder import ContextBuilder, DimContext
from src.llm import Message
from src.llm.provider import LLMProvider
from src.store.repository import Repository

log = logging.getLogger(__name__)

_POLICY = AgentCallPolicy(max_retries=2, backoff_seconds=1.5)


class DimState(TypedDict, total=False):
    doc_id: str
    dimension: str
    context: DimContext
    explorer_a_raw: dict[str, Any]
    explorer_b_raw: dict[str, Any]
    critic_raw: dict[str, Any]
    skip_explorer_a: bool


class DimSupervisor:
    """单维度 2+1 审核主管。

    模型分层：
      - explorer_model  : 快速/便宜模型（Explorer A/B，频繁调用）
      - critic_model    : 推理模型（Critic，需要深度分析）

    并发策略：
      - Explorer A 和 Explorer B 通过 ThreadPoolExecutor 并行执行
      - Critic 串行（需要看 A/B 全部结果）
    """

    def __init__(
        self,
        dimension: str,
        provider: LLMProvider,
        repo: Repository,
        *,
        explorer_model: str,          # Explorer A/B 用的模型（快/便宜）
        critic_model: str,            # Critic 用的模型（慢/推理强）
        explorer_a_temperature: float = 0.2,
        explorer_b_temperature: float = 0.0,
    ) -> None:
        self.dimension = dimension
        self._provider = provider
        self._repo = repo
        self._explorer_model = explorer_model
        self._critic_model = critic_model
        self._a_temp = explorer_a_temperature
        self._b_temp = explorer_b_temperature
        self._ctx_builder = ContextBuilder(repo)
        self._hooks = get_global_registry()

    # ── 公共入口 ─────────────────────────────────────────────────────────────

    def run(self, doc_id: str) -> AgentResult:
        """同步入口：build_context → A‖B 并发 → Critic 串行。"""
        import concurrent.futures

        self._hooks.fire("pre_agent_run",
                         role="dim_supervisor", dimension=self.dimension, doc_id=doc_id)
        try:
            # 1. 构建上下文
            ctx = self._ctx_builder.build(doc_id, self.dimension)

            # 2. Explorer A ‖ Explorer B 并发（线程池，因 LLM 调用是同步 IO）
            skip_a = self.dimension in OBJECTIVE_DIMENSIONS
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                fut_b = pool.submit(self._call_explorer, ctx, "b")
                if skip_a:
                    explorer_a_raw: dict[str, Any] = {}
                    explorer_b_raw = fut_b.result()
                else:
                    fut_a = pool.submit(self._call_explorer, ctx, "a")
                    # 同时等待 A 和 B，哪个先完成就先拿
                    explorer_a_raw = fut_a.result()
                    explorer_b_raw = fut_b.result()

            # 3. Critic 串行（需要 A/B 全部结果 + 推理模型）
            critic_raw = self._call_critic(ctx, explorer_a_raw, explorer_b_raw)

            state: DimState = {
                "doc_id": doc_id, "dimension": self.dimension, "context": ctx,
                "explorer_a_raw": explorer_a_raw,
                "explorer_b_raw": explorer_b_raw,
                "critic_raw": critic_raw,
                "skip_explorer_a": skip_a,
            }
            result = self._to_agent_result(state)
        except Exception as exc:
            log.exception("DimSupervisor [%s] 执行失败", self.dimension)
            result = AgentResult(
                dimension=self.dimension, verdict="uncertain", confidence=10,
                details=f"DimSupervisor 执行异常：{exc}", need_human_review=True,
            )
        self._hooks.fire("post_agent_run",
                         role="dim_supervisor", dimension=self.dimension, result=result)
        return result

    async def run_async(self, doc_id: str) -> AgentResult:
        """异步入口：在线程池中运行同步 run()，供 asyncio.gather 并发调用。"""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.run, doc_id)

        g = StateGraph(DimState)
        g.add_node("build_context", node_build_context)
        g.add_node("explorer_a", node_explorer_a)
    # ── LLM 调用 ─────────────────────────────────────────────────────────────

    def _call_explorer(self, ctx: DimContext, role: str) -> dict[str, Any]:
        temp = self._a_temp if role == "a" else self._b_temp
        system = build_explorer_system(self.dimension, role)
        user = build_explorer_user_prompt(
            ctx.chunks_text(),
            ctx.standards_text(),
            ctx.skills_text(),
        )

        def _do_call() -> dict[str, Any]:
            self._hooks.fire("pre_tool_call", "llm_call", {"role": role, "dim": self.dimension})
            raw = self._provider.call_text(
                [Message(role="system", content=system),
                 Message(role="user", content=user)],
                model=self._explorer_model,   # 用快速/便宜模型
                temperature=temp,
                max_tokens=1400,
            )
            data = parse_json_response(raw)
            if not data:
                raise ValueError(f"Explorer {role.upper()} 未返回有效 JSON")
            data["role"] = f"explorer_{role}"
            return data

        def _fallback() -> dict[str, Any]:
            return {
                "verdict_hint": "uncertain", "score_hint": 0, "confidence": 20,
                "reasoning": f"Explorer {role.upper()} LLM 调用失败",
                "findings": [], "evidence_refs": [], "role": f"explorer_{role}",
            }

        return with_retry(_do_call, _POLICY, fallback_fn=_fallback,
                          context_label=f"Explorer{role.upper()}/{self.dimension}")

    def _call_critic(
        self,
        ctx: DimContext,
        a_raw: dict[str, Any],
        b_raw: dict[str, Any],
    ) -> dict[str, Any]:
        # 在调用 LLM 前，用工具验证 evidence
        a_verified, b_verified = self._verify_evidences(ctx.doc_id, a_raw, b_raw)

        system = build_critic_system()
        user = build_critic_user_prompt(
            ctx.chunks_text(),
            ctx.standards_text(),
            json.dumps({**a_raw, "evidence_verified": a_verified}, ensure_ascii=False)[:3000],
            json.dumps({**b_raw, "evidence_verified": b_verified}, ensure_ascii=False)[:3000],
        )

        def _do_call() -> dict[str, Any]:
            raw = self._provider.call_text(
                [Message(role="system", content=system),
                 Message(role="user", content=user)],
                model=self._critic_model,
                temperature=0.0,
                max_tokens=1600,
            )
            data = parse_json_response(raw)
            if not data:
                raise ValueError("Critic 未返回有效 JSON")
            data["evidence_verified"] = a_verified and b_verified
            return data

        def _fallback() -> dict[str, Any]:
            # Critic 失败时：合并 B（更精确）+ A 特有的 high findings
            return self._fallback_merge(a_raw, b_raw, a_verified, b_verified)

        result = with_retry(_do_call, _POLICY, fallback_fn=_fallback,
                            context_label=f"Critic/{self.dimension}")

        # 处理 Critic 要求保存技能的情况
        extra = result.get("extra") or {}
        if extra.get("save_skill") and extra.get("skill_name"):
            self._maybe_save_skill(result, extra)

        return result

    def _verify_evidences(
        self,
        doc_id: str,
        a_raw: dict[str, Any],
        b_raw: dict[str, Any],
    ) -> tuple[bool, bool]:
        """用 verify_evidence_in_doc 工具验证 A/B 的 evidence_refs 是否真实存在。"""
        from src.harness.tools.verification import verify_evidence_in_doc
        from src.harness.tools.retrieval import set_repo as set_retrieval_repo
        set_retrieval_repo(self._repo)

        def _check_refs(raw: dict[str, Any]) -> bool:
            refs = raw.get("evidence_refs") or []
            if not refs:
                findings = raw.get("findings") or []
                refs = [f.get("evidence", "") for f in findings if isinstance(f, dict)]
            refs = [r for r in refs if r and len(r) > 10]
            if not refs:
                return True  # 没有 evidence 引用，视为通过
            # 取前 3 个验证
            verified_count = 0
            for ref in refs[:3]:
                result = verify_evidence_in_doc(doc_id=doc_id, evidence_text=str(ref))
                if result.get("found"):
                    verified_count += 1
            return verified_count >= max(1, len(refs[:3]) // 2)

        try:
            a_verified = _check_refs(a_raw)
            b_verified = _check_refs(b_raw)
        except Exception as e:
            log.warning("Evidence 验证失败: %s", e)
            a_verified = True
            b_verified = True
        return a_verified, b_verified

    def _fallback_merge(
        self,
        a_raw: dict[str, Any],
        b_raw: dict[str, Any],
        a_verified: bool,
        b_verified: bool,
    ) -> dict[str, Any]:
        """Critic LLM 失败时的 fallback：以 B 为基准，补充 A 的 high findings。"""
        base = b_raw if b_verified else a_raw
        verdict = str(base.get("verdict_hint", "uncertain")).lower()
        if verdict not in ("pass", "partial", "fail", "uncertain"):
            verdict = "uncertain"
        findings = list(base.get("findings") or [])
        # 补充 A 特有的 high findings（B 未报告的）
        if a_verified and a_raw:
            b_descs = {f.get("description", "") for f in findings if isinstance(f, dict)}
            for f in (a_raw.get("findings") or []):
                if (isinstance(f, dict) and
                        f.get("severity") == "high" and
                        f.get("description", "") not in b_descs):
                    findings.append(f)
        try:
            score = int(base.get("score_hint", 0))
        except (TypeError, ValueError):
            score = 0
        try:
            conf = int(base.get("confidence", 40))
        except (TypeError, ValueError):
            conf = 40
        return {
            "verdict": verdict,
            "score": score,
            "confidence": min(conf, 70),  # fallback 置信度上限 70
            "selected_from": "B" if b_verified else "merged",
            "evidence_verified": a_verified and b_verified,
            "reasoning": "Critic LLM 失败，自动合并 B + A high findings",
            "findings": findings,
            "human_review_required": True,
            "extra": {},
        }

    def _maybe_save_skill(self, critic_result: dict[str, Any], extra: dict[str, Any]) -> None:
        """置信度 ≥ 80 时保存技能到数据库。"""
        if critic_result.get("confidence", 0) < 80:
            return
        name = extra.get("skill_name", "")
        pattern = extra.get("skill_pattern", "")
        solution = extra.get("skill_solution", "")
        if not name or not solution:
            return
        try:
            skill_id = f"{self.dimension}_{name}_{uuid.uuid4().hex[:6]}"
            self._repo.upsert_skill(
                skill_id=skill_id,
                name=name,
                dimension=self.dimension,
                pattern=pattern or f"{self.dimension} 审核技能",
                solution=solution,
                tags=[self.dimension],
            )
            log.info("技能已保存: %s [%s]", name, self.dimension)
        except Exception as e:
            log.warning("保存技能失败: %s", e)

    # ── 结果转换 ─────────────────────────────────────────────────────────────

    def _to_agent_result(self, state: DimState) -> AgentResult:
        critic = state.get("critic_raw") or {}
        explorer_a = state.get("explorer_a_raw") or {}
        explorer_b = state.get("explorer_b_raw") or {}

        if not critic:
            # 图执行失败，fallback
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                confidence=10,
                details="DimSupervisor graph 未产出 critic 输出",
                need_human_review=True,
                extra={
                    "explorer_a": explorer_a,
                    "explorer_b": explorer_b,
                    "langgraph_path": "failed",
                },
            )

        crit = parse_critic_output(critic)
        findings = [
            Finding(
                severity=f.severity,
                description=f.description,
                evidence=f.evidence,
                rule_id=f.rule_id,
            )
            for f in crit.findings
        ]

        need_review = crit.human_review_required or should_human_review(
            {
                "verdict": crit.verdict,
                "confidence": crit.confidence,
                "evidence_verified": crit.evidence_verified,
                "selected_from": crit.selected_from,
                "findings": [f.model_dump() for f in crit.findings],
            },
            dimension=self.dimension,
        )

        result = AgentResult(
            dimension=self.dimension,
            verdict=crit.verdict,
            score=crit.score,
            confidence=crit.confidence,
            findings=findings,
            details=crit.reasoning[:500] if crit.reasoning else "",
            need_human_review=need_review,
            extra={
                "selected_from": crit.selected_from,
                "evidence_verified": crit.evidence_verified,
                "langgraph_path": "2plus1",
                "explorer_a_verdict": explorer_a.get("verdict_hint", ""),
                "explorer_b_verdict": explorer_b.get("verdict_hint", ""),
                "skill_saved": crit.skill_saved,
            },
        )

        # Hooks
        self._hooks.fire("pre_commit", result)
        return result
