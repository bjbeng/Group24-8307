"""Explorer：运行所有 SubAgent 并行审核，输出完整的跨维度结果集。

打标阶段：Explorer A（高召回）和 Explorer B（高精度）并行运行
审核阶段：只用一个 AuditExplorer（结合 A/B 最优偏置）

内部并发：ThreadPoolExecutor，每个 SubAgent 是独立线程
"""
from __future__ import annotations

import concurrent.futures
import logging
import time
from typing import Any, Literal

from src.agents.base import AgentResult
from src.harness.agent_group.sub_agent import (
    SubAgent,
    SubAgentConfig,
    Scenario,
    Role,
    build_sub_agents,
)
from src.harness.hooks.registry import get_global_registry

log = logging.getLogger(__name__)


class Explorer:
    """
    单个 Explorer：并行运行所有 SubAgent，返回 {dimension: AgentResult} 字典。

    role="a" → 高召回偏置（Explorer A）
    role="b" → 高精度偏置（Explorer B）
    role="audit" → 审核偏置（单 Explorer 审核阶段）
    """

    def __init__(
        self,
        role: Role,
        sub_agents: dict[str, SubAgent],
        *,
        explorer_model: str,
        vision_model: str = "",
        max_workers: int = 8,
    ) -> None:
        self.role = role
        self._sub_agents = sub_agents
        self._explorer_model = explorer_model
        self._vision_model = vision_model
        self._max_workers = max_workers
        self._hooks = get_global_registry()

    def run(
        self,
        doc_id: str,
        chunks: list[dict[str, Any]],
        image_chunks: list[dict[str, Any]] | None = None,
        scenario: Scenario = "s1",
        progress_cb=None,
    ) -> dict[str, AgentResult]:
        """并发运行所有 SubAgent，返回完整维度结果。

        Explorer A 和 B 完全相同（同一模型、同一 prompt），
        唯一区别是 temperature：A=0.2（采样多样），B=0.0（确定性）。
        """
        # A/B 唯一区别：temperature
        temperature = 0.2 if self.role == "a" else 0.0
        cfg = SubAgentConfig(
            role=self.role,
            scenario=scenario,
            explorer_model=self._explorer_model,  # A/B 共用同一模型
            vision_model=self._vision_model,
            temperature=temperature,              # 唯一差异
        )

        # 路由 chunks：文本 SubAgent 用文本 chunks，视觉 SubAgent 用 image_chunks
        text_chunks = chunks
        img_chunks = image_chunks or []

        results: dict[str, AgentResult] = {}
        t0 = time.perf_counter()
        log.info("Explorer [%s] 开始，%d 个 SubAgent，doc=%s",
                 self.role, len(self._sub_agents), doc_id)

        self._hooks.fire("pre_agent_run",
                         role=f"explorer_{self.role}", dimension="all", doc_id=doc_id)

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(self._sub_agents), self._max_workers),
            thread_name_prefix=f"explorer_{self.role}",
        ) as pool:
            futs: dict[concurrent.futures.Future, str] = {}
            for dim, agent in self._sub_agents.items():
                # 视觉 SubAgent 只在有图片时运行
                if agent.requires_vision and not img_chunks:
                    continue
                fut = pool.submit(
                    self._run_one, agent, text_chunks, cfg, img_chunks
                )
                futs[fut] = dim

            for fut in concurrent.futures.as_completed(futs):
                dim = futs[fut]
                try:
                    res = fut.result(timeout=120)
                    results[dim] = res
                    log.debug("  SubAgent [%s/%s] verdict=%s conf=%s",
                              self.role, dim, res.verdict, res.confidence)
                except concurrent.futures.TimeoutError:
                    log.warning("  SubAgent [%s/%s] 超时", self.role, dim)
                    results[dim] = AgentResult(
                        dimension=dim, verdict="uncertain", confidence=10,
                        details="SubAgent 超时", need_human_review=True,
                    )
                except Exception as e:
                    log.exception("  SubAgent [%s/%s] 异常", self.role, dim)
                    results[dim] = AgentResult(
                        dimension=dim, verdict="uncertain", confidence=10,
                        details=f"SubAgent 异常: {e}", need_human_review=True,
                    )
                if progress_cb:
                    try:
                        progress_cb(dim, results[dim].verdict)
                    except Exception:
                        pass

        elapsed = time.perf_counter() - t0
        log.info("Explorer [%s] 完成，耗时 %.1fs，%d 维度 dims=%s",
                 self.role, elapsed, len(results), list(results.keys()))
        return results

    @staticmethod
    def _run_one(
        agent: SubAgent,
        chunks: list[dict[str, Any]],
        cfg: SubAgentConfig,
        image_chunks: list[dict[str, Any]],
    ) -> AgentResult:
        """在独立线程里运行单个 SubAgent（异常不向上抛，由 caller 捕获）。"""
        return agent.run(chunks, cfg, image_chunks if agent.requires_vision else None)


class ExplorerFactory:
    """根据配置构建 Explorer 实例（A/B/Audit）。

    A 和 B 使用完全独立的 provider + sub-agents：
    - 避免线程安全问题（agent 内部有 text_model/temperature 状态）
    - 支持 A/B 使用不同服务商（DeepSeek vs Qwen vs Gemini）
    """

    def __init__(
        self,
        config: dict[str, Any],
        repo: Any,
        scenario: Scenario,
        *,
        max_workers: int = 8,
    ) -> None:
        from src.llm.factory import build_provider_for_role

        self._scenario = scenario
        self._max_workers = max_workers
        llm_cfg = config.get("llm", {})

        # ── 各角色 model 名称 ────────────────────────────────────────────
        self._model_a = llm_cfg.get("explorer_a", {}).get(
            "model", llm_cfg.get("text_model", "mock")
        )
        self._model_b = llm_cfg.get("explorer_b", {}).get(
            "model", llm_cfg.get("text_model", "mock")
        )
        vision_model = llm_cfg.get("vision", {}).get(
            "model", llm_cfg.get("vision_model", "")
        )
        self._vision_model = vision_model
        critic_model = llm_cfg.get("critic", {}).get(
            "model", llm_cfg.get("text_model", "mock")
        )

        # ── 各角色独立 Provider ──────────────────────────────────────────
        provider_a = build_provider_for_role(config, "explorer_a")
        provider_b = build_provider_for_role(config, "explorer_b")

        # ── 为 A/B 各建一套独立的 sub-agent 实例（避免线程竞态）────────
        self._sub_agents_a = build_sub_agents(
            provider_a, repo, scenario,
            explorer_model=self._model_a,
            critic_model=critic_model,
            vision_model=vision_model,
        )
        self._sub_agents_b = build_sub_agents(
            provider_b, repo, scenario,
            explorer_model=self._model_b,
            critic_model=critic_model,
            vision_model=vision_model,
        )

        log.info(
            "ExplorerFactory: scenario=%s A_model=%s B_model=%s vision=%s critic=%s",
            scenario, self._model_a, self._model_b, vision_model, critic_model,
        )

    def build(self, role: Role) -> Explorer:
        if role == "a":
            return Explorer(
                role="a",
                sub_agents=self._sub_agents_a,
                explorer_model=self._model_a,
                vision_model=self._vision_model,
                max_workers=self._max_workers,
            )
        return Explorer(
            role=role,
            sub_agents=self._sub_agents_b,
            explorer_model=self._model_b,
            vision_model=self._vision_model,
            max_workers=self._max_workers,
        )
