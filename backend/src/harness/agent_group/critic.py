"""CrossDimensionCritic：跨维度仲裁，从 Explorer A/B 的结果中选择/合并最优内容。

职责：
1. 逐维度对比 A/B 结论，选择更可靠的
2. 验证证据（verify_evidence_in_doc）
3. 跨维度矛盾检查（C1 pass 但 C4 fail 等）
4. 高难度 case 自动保存 Skill
5. 输出最终 {dimension: AgentResult} + confidence 分级
"""
from __future__ import annotations

import json
import logging
from typing import Any

from src.agents.base import AgentResult, Finding, parse_json_response
from src.harness.guardrails.human_review import (
    cross_dim_consistency_check,
    should_human_review,
)
from src.llm import Message
from src.llm.provider import LLMProvider
from src.store.repository import Repository

log = logging.getLogger(__name__)

# Critic 仲裁规则
_CRITIC_SYSTEM = """你是跨维度仲裁审核官。

你会收到同一文档的两份审核结果（Explorer A = 高召回，Explorer B = 高精度），
以及原文部分摘录。你的任务：

1. **逐维度仲裁**：
   - A=B 且证据有效 → 采用，confidence = (A+B)/2
   - A=uncertain, B=fail → 优先信 B
   - A=partial, B=pass → 看 B 的证据是否充分覆盖
   - A=pass, B=fail → 高分歧，必须写 ≥100 字裁决理由

2. **证据验证**：A/B 引用的证据必须能在原文中找到，否则降级或剔除

3. **跨维度一致性**：检查维度间逻辑矛盾（如 C1 pass 但 C4 悬空引用严重）

只输出 JSON（不要围栏）：
{
  "dimensions": {
    "<dim_name>": {
      "verdict": "pass|partial|fail|uncertain",
      "score": 0-12,
      "confidence": 0-100,
      "selected_from": "A|B|merged|critic_only",
      "evidence_verified": true|false,
      "reasoning": "...",
      "findings": [{"severity":"high|medium|low","description":"","evidence":"","rule_id":""}],
      "human_review_required": false
    }
  },
  "cross_dim_warnings": ["..."],
  "overall_verdict": "pass|partial|fail|uncertain",
  "overall_score": 0-100
}"""


class CrossDimensionCritic:
    """跨维度仲裁官。"""

    def __init__(
        self,
        provider: LLMProvider,
        critic_model: str,
        repo: Repository | None = None,
    ) -> None:
        self._provider = provider
        self._critic_model = critic_model
        self._repo = repo

    def run(
        self,
        doc_id: str,
        a_results: dict[str, AgentResult],
        b_results: dict[str, AgentResult],
        sample_chunks: list[dict[str, Any]] | None = None,
    ) -> dict[str, AgentResult]:
        """
        仲裁 A/B 全部维度结果，返回最终 {dimension: AgentResult}。
        LLM 失败时 fallback 到规则仲裁。
        """
        # 先用规则做一次初步仲裁（快速且不依赖 LLM）
        rule_merged = self._rule_merge(a_results, b_results)

        # 高分歧维度列表（A/B verdict 不一致）
        divergent = [
            dim for dim in rule_merged
            if a_results.get(dim) and b_results.get(dim) and
            (a_results[dim].verdict != b_results[dim].verdict)
        ]

        # 只有高分歧维度才调 LLM（省 token）
        if divergent and len(divergent) <= 6:
            try:
                llm_merged = self._llm_arbitrate(
                    doc_id, a_results, b_results, divergent, sample_chunks
                )
                rule_merged.update(llm_merged)
                log.info("Critic LLM 仲裁了 %d 个分歧维度", len(llm_merged))
            except Exception as e:
                log.warning("Critic LLM 失败，使用规则仲裁: %s", e)

        # 跨维度矛盾检查
        warnings = cross_dim_consistency_check(
            {k: v.to_dict() for k, v in rule_merged.items()}
        )
        if warnings:
            log.warning("跨维度矛盾: %s", warnings)
            # 降级相关维度置信度
            for w in warnings:
                for dim in rule_merged:
                    if dim in w:
                        r = rule_merged[dim]
                        rule_merged[dim] = AgentResult(
                            dimension=r.dimension,
                            verdict=r.verdict,
                            score=r.score,
                            confidence=max(0, r.confidence - 15),
                            findings=r.findings,
                            details=r.details + f"\n[跨维度警告] {w}",
                            need_human_review=True,
                            extra={**r.extra, "cross_dim_warning": w},
                        )

        return rule_merged

    # ── 规则仲裁（不调 LLM）────────────────────────────────────────────────

    def _rule_merge(
        self,
        a: dict[str, AgentResult],
        b: dict[str, AgentResult],
    ) -> dict[str, AgentResult]:
        """基于规则的快速仲裁：优先取置信度高的，A/B 一致时合并。"""
        all_dims = set(a.keys()) | set(b.keys())
        merged: dict[str, AgentResult] = {}

        for dim in all_dims:
            ra = a.get(dim)
            rb = b.get(dim)

            if ra is None and rb is not None:
                merged[dim] = _tag(rb, "B")
            elif rb is None and ra is not None:
                merged[dim] = _tag(ra, "A")
            elif ra is not None and rb is not None:
                merged[dim] = self._merge_two(ra, rb)
            # 两者都 None：不加入结果

        return merged

    def _merge_two(self, ra: AgentResult, rb: AgentResult) -> AgentResult:
        """合并两个 AgentResult。"""
        # A/B 一致：取平均置信度
        if ra.verdict == rb.verdict:
            avg_conf = (ra.confidence + rb.confidence) // 2
            avg_score = ((ra.score or 0) + (rb.score or 0)) // 2
            # 合并 findings（去重）
            findings = list(ra.findings)
            seen = {f.description for f in findings}
            for f in rb.findings:
                if f.description not in seen:
                    findings.append(f)
                    seen.add(f.description)
            return AgentResult(
                dimension=ra.dimension,
                verdict=ra.verdict,
                score=avg_score,
                confidence=avg_conf,
                findings=findings,
                details=rb.details or ra.details,
                need_human_review=(ra.need_human_review or rb.need_human_review
                                   or avg_conf < 50),
                extra={**ra.extra, "selected_from": "merged",
                       "a_verdict": ra.verdict, "b_verdict": rb.verdict},
            )

        # A/B 分歧：倾向于保守（选 verdict 更严格的）
        _SEVERITY = {"fail": 3, "partial": 2, "uncertain": 1, "pass": 0}
        if _SEVERITY.get(ra.verdict, 0) >= _SEVERITY.get(rb.verdict, 0):
            chosen, tag = ra, "A"
        else:
            chosen, tag = rb, "B"

        # 低置信（分歧场景）
        return AgentResult(
            dimension=chosen.dimension,
            verdict=chosen.verdict,
            score=chosen.score,
            confidence=min(chosen.confidence, 70),  # 分歧时置信度上限 70
            findings=chosen.findings,
            details=f"[A≠B 规则选{tag}] " + chosen.details,
            need_human_review=True,
            extra={**chosen.extra, "selected_from": tag,
                   "a_verdict": ra.verdict, "b_verdict": rb.verdict},
        )

    # ── LLM 仲裁（只处理高分歧维度）────────────────────────────────────────

    def _llm_arbitrate(
        self,
        doc_id: str,
        a: dict[str, AgentResult],
        b: dict[str, AgentResult],
        divergent_dims: list[str],
        sample_chunks: list[dict[str, Any]] | None,
    ) -> dict[str, AgentResult]:
        """调用 critic_model 仲裁高分歧维度。"""
        # 构建 payload：只发高分歧维度的结果
        a_payload = {d: a[d].to_dict() for d in divergent_dims if d in a}
        b_payload = {d: b[d].to_dict() for d in divergent_dims if d in b}
        excerpt = ""
        if sample_chunks:
            texts = [c.get("content", "")[:500] for c in sample_chunks[:4]]
            excerpt = "\n---\n".join(texts)

        user = (
            f"## 高分歧维度列表\n{divergent_dims}\n\n"
            f"## Explorer A 结果\n{json.dumps(a_payload, ensure_ascii=False)[:4000]}\n\n"
            f"## Explorer B 结果\n{json.dumps(b_payload, ensure_ascii=False)[:4000]}\n\n"
            f"## 原文摘录（前段）\n{excerpt[:2000]}\n"
        )

        raw = self._provider.call_text(
            [Message(role="system", content=_CRITIC_SYSTEM),
             Message(role="user", content=user)],
            model=self._critic_model,
            temperature=0.0,
            max_tokens=2000,
        )
        data = parse_json_response(raw)
        if not data or "dimensions" not in data:
            raise ValueError("Critic LLM 未返回有效 JSON")

        result: dict[str, AgentResult] = {}
        for dim, dim_data in data.get("dimensions", {}).items():
            if dim not in divergent_dims:
                continue
            verdict = str(dim_data.get("verdict", "uncertain")).lower()
            if verdict not in ("pass", "partial", "fail", "uncertain"):
                verdict = "uncertain"
            try:
                score = int(dim_data.get("score", 0))
            except (TypeError, ValueError):
                score = 0
            try:
                conf = int(dim_data.get("confidence", 50))
            except (TypeError, ValueError):
                conf = 50

            findings = [
                Finding(
                    severity=f.get("severity", "medium"),
                    description=f.get("description", ""),
                    evidence=f.get("evidence", ""),
                    rule_id=f.get("rule_id"),
                )
                for f in (dim_data.get("findings") or [])
                if isinstance(f, dict)
            ]
            result[dim] = AgentResult(
                dimension=dim,
                verdict=verdict,
                score=max(0, min(12, score)),
                confidence=max(0, min(100, conf)),
                findings=findings,
                details=str(dim_data.get("reasoning", ""))[:500],
                need_human_review=(
                    bool(dim_data.get("human_review_required"))
                    or should_human_review(dim_data, dimension=dim)
                ),
                extra={
                    "selected_from": dim_data.get("selected_from", "critic"),
                    "evidence_verified": bool(dim_data.get("evidence_verified")),
                    "critic_model": self._critic_model,
                },
            )
        return result


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def _tag(result: AgentResult, tag: str) -> AgentResult:
    """给 AgentResult 加 selected_from 标记。"""
    return AgentResult(
        dimension=result.dimension,
        verdict=result.verdict,
        score=result.score,
        confidence=result.confidence,
        findings=result.findings,
        details=result.details,
        need_human_review=result.need_human_review,
        extra={**result.extra, "selected_from": tag},
    )
