"""AuditOrchestrator：协调所有维度，2+1 维度用 DimSupervisor，规则维度用现有 agent。

维度分类：
- LLM_2PLUS1_DIMENSIONS: C2/C3/C5/E2/L2 → DimSupervisor（Explorer A‖B 并发 + Critic 推理模型）
- OBJECTIVE_DIMENSIONS:   C1/C4/E1        → 现有规则 agent（不调 LLM）
- RULE_ONLY_DIMENSIONS:   T1/T2/T3        → src.metrics.compute

并发策略（三级）：
  维度级：asyncio.gather 按优先级分组并行
    组1（快）: C1/C4/E1    规则计算，无 LLM
    组2（中）: C2/C3/E2/L2 Explorer 模型（快/便宜）
    组3（重）: C5           LangGraph（较复杂）
    组4（即）: T1/T2/T3     metrics，无 LLM
  Explorer 级：ThreadPoolExecutor 让 A‖B 并行
  批量级：asyncio.Semaphore 控制并发文档数

模型分层：
  explorer_model  ← 快速/便宜（qwen-plus / Qwen2.5-7B）
  critic_model    ← 推理强（QwQ-32B / deepseek-reasoner）
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import time
from pathlib import Path
from typing import Any

from src.agents import (
    C1StructureAgent,
    C4ReferenceAgent,
    E1StaffingAgent,
)
from src.agents.base import AgentResult
from src.agents.standards_seed import ensure_demo_standards
from src.chunk import Chunk, chunk_docx_blocks
from src.config import get_default_config
from src.harness.agent_group.dim_supervisor import DimSupervisor
from src.harness.agent_group.roles import (
    LLM_2PLUS1_DIMENSIONS,
    OBJECTIVE_DIMENSIONS,
    RULE_ONLY_DIMENSIONS,
)
from src.harness.guardrails.human_review import cross_dim_consistency_check
from src.harness.hooks.registry import get_global_registry
from src.harness.session.doc_session import DocSession, DocSessionState
from src.llm import LLMProvider, build_provider
from src.metrics import MetricsContext, compute_metrics
from src.parse import convert_doc_to_docx, parse_docx
from src.pipeline.audit import AuditResult, derive_doc_id
from src.store import Repository

log = logging.getLogger(__name__)


class AuditOrchestrator:
    """多维度审核编排器（替代 AuditPipeline，支持 2+1 架构）。

    与 AuditPipeline 的区别：
    - C2/C3/C5/E2/L2 → DimSupervisor（完整 2+1 + 技能库）
    - C1/C4/E1       → 保留现有规则实现
    - T1/T2/T3       → 保留 metrics
    - 增加跨维度矛盾检查（CrossDimCritic）
    - 增加 DocSession 断点续传
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        provider: LLMProvider | None = None,
        repo: Repository | None = None,
        session_db: str | None = None,
    ) -> None:
        self.config = config or get_default_config()
        self.provider = provider or build_provider(self.config)
        db_path = self.config.get("paths", {}).get("db_path", ":memory:")
        self.repo = repo or Repository(db_path)
        self._hooks = get_global_registry()

        # 初始化标准库
        ensure_demo_standards(self.repo)

        # 会话管理
        self._session_db = session_db or db_path
        self._session = DocSession(self._session_db)

        # ── 模型分层配置 ────────────────────────────────────────────────────
        llm_cfg = self.config.get("llm", {}) or {}
        # Explorer A/B：快速/便宜模型，频繁调用
        self._explorer_model = llm_cfg.get(
            "explorer_model",
            llm_cfg.get("text_model", "Qwen3-2B"),
        )
        # Critic：推理强的模型，每维度只调一次
        self._critic_model = llm_cfg.get(
            "critic_model",
            llm_cfg.get("reasoning_model", self._explorer_model),
        )
        self._a_temp = float(llm_cfg.get("explorer_a_temperature", 0.2))
        self._b_temp = float(llm_cfg.get("explorer_b_temperature", 0.0))
        # ── 并发控制 ────────────────────────────────────────────────────────
        # 每个维度组内的最大并发维度数（避免 API 限流）
        self._dim_concurrency = int(
            self.config.get("audit", {}).get("dim_concurrency", 4)
        )

        self._rule_agents = self._build_rule_agents()
        self._supervisors: dict[str, DimSupervisor] = {}  # 按需创建

        log.info(
            "AuditOrchestrator 初始化完成 | explorer=%s critic=%s concurrency=%d",
            self._explorer_model, self._critic_model, self._dim_concurrency,
        )

    # ── 公共入口 ─────────────────────────────────────────────────────────────

    def run(self, doc_path: str | Path) -> AuditResult:
        """同步入口（兼容旧 AuditPipeline.run 接口）。"""
        t0 = time.perf_counter()
        path = Path(doc_path).resolve()
        doc_id = derive_doc_id(path)
        log.info("Orchestrator 开始审核 %s (doc_id=%s)", path.name, doc_id)

        # 会话创建/恢复
        existing = self._session.get_by_doc(doc_id)
        if existing and existing[0].status not in ("done", "failed"):
            sess = existing[0]
            log.info("恢复会话 %s，已完成维度: %s", sess.session_id, sess.completed_dims)
        else:
            sess = self._session.create(doc_id, str(path))

        self._session.update_status(sess.session_id, "ingesting")
        parse_ok, chunks = self._ingest(path, doc_id)

        self._session.update_status(sess.session_id, "auditing")
        dim_results: dict[str, AgentResult] = {}

        # 已完成的维度从 labels 表恢复
        dim_results.update(self._restore_completed(doc_id, sess))

        all_dims = list(LLM_2PLUS1_DIMENSIONS | OBJECTIVE_DIMENSIONS)

        if parse_ok and chunks:
            remaining = sess.remaining_dims(all_dims)
            # ── 分组并发执行 ──────────────────────────────────────────────
            # 组1：规则维度（无 LLM，最快）
            group_rule   = [d for d in remaining if d in OBJECTIVE_DIMENSIONS]
            # 组2：LLM 轻量维度（Explorer 快模型）
            group_llm    = [d for d in remaining
                            if d in LLM_2PLUS1_DIMENSIONS and d != "C5_logic"]
            # 组3：C5（LangGraph，单独跑）
            group_c5     = [d for d in remaining if d == "C5_logic"]

            for group_name, group in [
                ("rule", group_rule),
                ("llm", group_llm),
                ("c5", group_c5),
            ]:
                if not group:
                    continue
                group_results = self._run_group_concurrent(
                    group, doc_id, chunks, group_name
                )
                for dim, res in group_results.items():
                    dim_results[dim] = res
                    self._persist(doc_id, res)
                    if res.verdict != "uncertain" or not res.details.startswith("维度执行异常"):
                        self._session.mark_dim_done(sess.session_id, dim)
                    else:
                        self._session.mark_dim_failed(sess.session_id, dim)

        # Metrics T1/T2/T3
        elapsed = time.perf_counter() - t0
        ctx = MetricsContext(
            doc_path=path, chunks=chunks, elapsed_seconds=elapsed,
            input_format=path.suffix.lower(), parse_succeeded=parse_ok,
        )
        for dim, res in compute_metrics(ctx).items():
            dim_results[dim] = res

        # 跨维度矛盾检查
        warnings = cross_dim_consistency_check(
            {k: v.to_dict() for k, v in dim_results.items()}
        )
        if warnings:
            log.warning("跨维度矛盾: %s", warnings)

        self._session.update_status(sess.session_id, "aggregating")
        overall_verdict, overall_score = self._aggregate(dim_results)

        result = AuditResult(
            doc_id=doc_id,
            doc_name=path.name,
            review_timestamp=datetime.datetime.now().isoformat(),
            dimensions={k: v.to_dict() for k, v in dim_results.items()},
            overall_verdict=overall_verdict,
            overall_score=overall_score,
            need_human_review=any(r.need_human_review for r in dim_results.values()),
            elapsed_seconds=time.perf_counter() - t0,
        )

        self._session.finish(sess.session_id)
        self._hooks.fire("post_batch", batch_id=doc_id,
                         results=[result.to_dict()])
        return result

    async def run_async(self, doc_path: str | Path) -> AuditResult:
        """异步入口，供 BatchJobManager 调用。"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.run, doc_path)

    # ── 分组并发执行 ─────────────────────────────────────────────────────────

    def _run_group_concurrent(
        self,
        dims: list[str],
        doc_id: str,
        chunks: list[Chunk],
        group_name: str,
    ) -> dict[str, AgentResult]:
        """用 ThreadPoolExecutor 并发跑一组维度，受 _dim_concurrency 限制。"""
        import concurrent.futures

        results: dict[str, AgentResult] = {}
        log.info("并发执行维度组 [%s]: %s", group_name, dims)
        t0 = time.perf_counter()

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(dims), self._dim_concurrency)
        ) as pool:
            futs = {
                pool.submit(self._run_dimension, dim, doc_id, chunks): dim
                for dim in dims
            }
            for fut in concurrent.futures.as_completed(futs):
                dim = futs[fut]
                try:
                    res = fut.result()
                    results[res.dimension] = res
                    log.info("  维度完成 [%s] verdict=%s conf=%s",
                             dim, res.verdict, res.confidence)
                except Exception as e:
                    log.exception("  维度异常 [%s]", dim)
                    results[dim] = AgentResult(
                        dimension=dim, verdict="uncertain", confidence=10,
                        details=f"维度执行异常: {e}", need_human_review=True,
                    )

        log.info("维度组 [%s] 完成，耗时 %.1fs", group_name, time.perf_counter() - t0)
        return results

    # ── 维度路由 ─────────────────────────────────────────────────────────────

    def _run_dimension(
        self, dim: str, doc_id: str, chunks: list[Chunk]
    ) -> AgentResult:
        if dim in LLM_2PLUS1_DIMENSIONS:
            return self._get_supervisor(dim).run(doc_id)
        if dim in OBJECTIVE_DIMENSIONS:
            return self._run_rule_agent(dim, chunks)
        # fallback
        log.warning("未知维度 %s，跳过", dim)
        return AgentResult(dimension=dim, verdict="uncertain", confidence=0,
                           details=f"未知维度: {dim}", need_human_review=True)

    def _get_supervisor(self, dim: str) -> DimSupervisor:
        if dim not in self._supervisors:
            self._supervisors[dim] = DimSupervisor(
                dimension=dim,
                provider=self.provider,
                repo=self.repo,
                explorer_model=self._explorer_model,   # 快速/便宜
                critic_model=self._critic_model,        # 推理强
                explorer_a_temperature=self._a_temp,
                explorer_b_temperature=self._b_temp,
            )
        return self._supervisors[dim]

    def _run_rule_agent(self, dim: str, chunks: list[Chunk]) -> AgentResult:
        agent = self._rule_agents.get(dim)
        if agent is None:
            return AgentResult(dimension=dim, verdict="uncertain", confidence=0,
                               details=f"规则 agent {dim} 未注册", need_human_review=True)
        rows = [c.to_row() for c in chunks]
        if dim == "E1_staffing":
            rows = [r for r in rows if "E1_staffing" in (r.get("dimensions") or [])]
            if not rows:
                return AgentResult(dimension=dim, verdict="uncertain", confidence=20,
                                   details="未找到人员配备相关段落", need_human_review=True)
        return agent.run(rows)

    # ── 初始化 ───────────────────────────────────────────────────────────────

    def _build_rule_agents(self) -> dict[str, Any]:
        return {
            "C1_structure": C1StructureAgent(self.provider, self._text_model),
            "C4_reference": C4ReferenceAgent(self.provider, self._text_model),
            "E1_staffing":  E1StaffingAgent(self.provider, self._text_model),
        }

    # ── 文档解析 ─────────────────────────────────────────────────────────────

    def _ingest(self, path: Path, doc_id: str) -> tuple[bool, list[Chunk]]:
        cfg = self.config
        out_dir = Path(cfg["paths"]["data_dir"]) / "tmp" / doc_id
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            if path.suffix.lower() == ".doc":
                path = convert_doc_to_docx(
                    path, out_dir,
                    timeout=cfg["parse"]["doc_to_docx_timeout"],
                )
            if path.suffix.lower() in (".docx", ".docm"):
                image_dir = Path(cfg["paths"]["images_dir"]) / doc_id
                blocks = parse_docx(path, image_out_dir=image_dir)
            else:
                log.error("暂不支持 %s 格式", path.suffix)
                return False, []
            chunks = chunk_docx_blocks(
                blocks, doc_id=doc_id,
                max_tokens=cfg["chunk"]["max_tokens"],
                table_inline_rows=cfg["chunk"]["table_inline_rows"],
            )
            # 维度路由
            from src.pipeline.audit import assign_dimensions
            assign_dimensions(chunks)
            self.repo.upsert_chunks(chunks)
            return True, chunks
        except Exception as e:
            log.error("Ingest 失败 [%s]: %s", path.name, e)
            return False, []

    # ── 持久化与恢复 ─────────────────────────────────────────────────────────

    def _persist(self, doc_id: str, result: AgentResult) -> None:
        import json as _json
        try:
            self.repo.upsert_label(
                label_id=f"{doc_id}__{result.dimension}__audit",
                doc_id=doc_id,
                dimension=result.dimension,
                pipeline="audit",
                final_verdict=result.verdict,
                score=result.score,
                confidence=result.confidence,
                findings=[f.to_dict() for f in result.findings],
                extra=result.extra,
                need_human_review=result.need_human_review,
                human_signoff=False,
            )
        except Exception as e:
            log.warning("持久化 %s 失败: %s", result.dimension, e)

    def _restore_completed(
        self, doc_id: str, sess: DocSessionState
    ) -> dict[str, AgentResult]:
        if not sess.completed_dims:
            return {}
        results: dict[str, AgentResult] = {}
        for dim in sess.completed_dims:
            labels = self.repo.get_labels(doc_id, pipeline="audit")
            for lbl in labels:
                if lbl.get("dimension") == dim:
                    from src.agents.base import Finding as _Finding
                    findings = []
                    for f in (lbl.get("findings") or []):
                        if isinstance(f, dict):
                            findings.append(_Finding(
                                severity=f.get("severity", "medium"),
                                description=f.get("description", ""),
                                evidence=f.get("evidence", ""),
                                rule_id=f.get("rule_id"),
                            ))
                    results[dim] = AgentResult(
                        dimension=dim,
                        verdict=lbl.get("final_verdict", "uncertain"),
                        score=lbl.get("score"),
                        confidence=lbl.get("confidence", 0),
                        findings=findings,
                        extra=lbl.get("extra") or {},
                        need_human_review=bool(lbl.get("need_human_review")),
                    )
                    break
        return results

    # ── 汇总 ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _aggregate(dim_results: dict[str, AgentResult]) -> tuple[str, int]:
        verdicts = [r.verdict for r in dim_results.values()]
        total = sum(r.score or 0 for r in dim_results.values())
        if not verdicts:
            return "uncertain", 0
        if "fail" in verdicts:
            return "fail", total
        if all(v == "pass" for v in verdicts):
            return "pass", total
        if "uncertain" in verdicts:
            return "uncertain", total
        return "partial", total

    def close(self) -> None:
        try:
            self.repo.close()
            self._session.close()
        except Exception:
            pass
