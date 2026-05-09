"""C3 文字及语法 —— 全文文本块 + 并行 LLM 检查通顺性、标点、缩略词注释。"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any

from src.agents.base import AgentResult, BaseAgent, parse_json_response
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
from src.store.repository import Repository

if TYPE_CHECKING:
    from src.pipeline.audit import StandardCache


log = logging.getLogger(__name__)

_DIM = "C3_language"

# 每个 batch 最多多少个 chunk（控制并行粒度）
_BATCH_CHUNK_SIZE = 10
# 每个 batch 最多多少字符（控制 LLM context）
_BATCH_CHAR_LIMIT = 4500
# 最大并发 LLM 调用数
_MAX_CONCURRENT_LLM_CALLS = 8


def _split_into_batches(refs: list[ChunkRef]) -> list[list[ChunkRef]]:
    """按 chunk 数量切分 batch，每批最多 _BATCH_CHUNK_SIZE 个 chunk。"""
    batches: list[list[ChunkRef]] = []
    for i in range(0, len(refs), _BATCH_CHUNK_SIZE):
        batches.append(refs[i : i + _BATCH_CHUNK_SIZE])
    return batches


def _build_batch_prompt(
    batch_refs: list[ChunkRef],
    snippets: list[dict[str, Any]],
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
        "你是中文技术文档审校编辑，参照 GBT1.1 对语言文字的基本要求。"
        "检查：语句是否明显不通顺；标点是否明显误用；首次出现的缩略词是否缺少中文注释。"
        "只报告有依据的问题；无问题则 verdict=pass, score=12。\n\n"
        "输出格式要求：\n"
        "每个 finding 必须包含：\n"
        "- severity: high/medium/low\n"
        "- description: 问题描述\n"
        "- evidence: 原文证据\n"
        "- rule_id: 规则依据ID（如 GBT1.1-2020 5.2）\n"
        "- is_problem: true（是否有问题）\n"
        "- problem_type: 问题类型（如\"标点误用\"、\"错别字\"、\"缩略词未注释\"等）\n"
        "- rule_basis: 规则依据原文（如\"依据 GB/T 1.1-2020 第5.2条：...\"）\n"
        "- correction_suggestion: 具体修改建议\n"
        "- chunk_id: 出问题的 chunk_id\n"
        "- section_path: chunk 所属章节路径\n"
        "- page_number: 所在页码（page_start）\n"
        "- anchor_text: 锚文本片段"
    )
    user = (
        "## GBT1.1 相关摘要（参考）\n"
        f"{format_snippets_for_prompt(snippets)}\n\n"
        "## 文档段落（本次batch）\n"
        f"{sampled}\n"
    )
    return system, user


class C3LanguageAgent(BaseAgent):
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
        # 全文收集所有 TEXT 块（不过滤、不抽样）
        all_refs = collect_chunks_all(chunks, chunk_types=("TEXT",), seed=42)
        if not all_refs:
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                score=0,
                confidence=15,
                details="无正文可检查语言规范。",
                need_human_review=True,
            )
        log.info("C3 全文检查：共 %d 个 TEXT chunk，将分为 %d 个 batch 并发执行",
                 len(all_refs), (len(all_refs) + _BATCH_CHUNK_SIZE - 1) // _BATCH_CHUNK_SIZE)

        # 获取标准条款片段（所有 batch 共用）
        if self.standard_cache is not None:
            snippets = self.standard_cache.get(_DIM) or []
        else:
            snippets = []
        if not snippets:
            sample_text = " ".join(r.excerpt[:100] for r in all_refs[:5])
            snippets = retrieve_standard_snippets(self.repo, _DIM, sample_text[:600], top_k=3)
        if not snippets:
            snippets = demo_standards_for_prompt(_DIM)

        # 分批
        batches = _split_into_batches(all_refs)

        # 建立 chunk_id → ChunkRef 映射（用于后续补全Finding字段）
        ref_map: dict[str, ChunkRef] = {r.chunk_id: r for r in all_refs}

        # 并发调 LLM
        all_findings: list = []
        batch_errors: list[str] = []
        batch_count = 0

        max_workers = min(self.max_concurrent_llm, len(batches))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(self._run_batch, batch, snippets, batch_idx): idx
                for idx, batch in enumerate(batches)
            }
            for future in as_completed(futures):
                batch_idx = futures[future]
                try:
                    batch_findings, batch_error = future.result()
                    all_findings.extend(batch_findings)
                    if batch_error:
                        batch_errors.append(batch_error)
                    batch_count += 1
                    log.debug("C3 batch %d/%d 完成（findings=%d）",
                              batch_count, len(batches), len(batch_findings))
                except Exception as e:
                    log.warning("C3 batch %d 执行异常: %s", batch_idx, e)
                    batch_errors.append(str(e))

        # 用 ChunkRef 补全每条 finding 的定位字段
        for f in all_findings:
            cid = getattr(f, "chunk_id", None) or ""
            if cid in ref_map:
                ref = ref_map[cid]
                if not getattr(f, "section_path", None):
                    f.section_path = ref.section_path
                if getattr(f, "paragraph_index", -1) < 0:
                    f.paragraph_index = ref.page_start
                if not getattr(f, "anchor_text", None):
                    f.anchor_text = ref.anchor_text

        # 汇总 verdict / score
        verdict, score, confidence = self._derive_from_findings(all_findings)

        return AgentResult(
            dimension=self.dimension,
            verdict=verdict,
            score=score,
            confidence=confidence,
            findings=all_findings,
            details=(
                f"全文 {len(all_refs)} chunk 分为 {len(batches)} 批并发检查，"
                f"发现问题 {len(all_findings)} 条"
                + (f"；批处理异常: {'; '.join(batch_errors[:3])}" if batch_errors else "")
            ),
            extra={
                "total_chunks": len(all_refs),
                "total_batches": len(batches),
                "batches_succeeded": batch_count - len(batch_errors),
                "sampled_chars": sum(len(r.excerpt) for r in all_refs),
            },
            need_human_review=verdict in ("uncertain", "fail") or len(batch_errors) > len(batches) // 2,
        )

    def _run_batch(
        self,
        batch: list[ChunkRef],
        snippets: list[dict[str, Any]],
        batch_idx: int,
    ) -> tuple[list, str | None]:
        """执行单个 batch 的 LLM 调用。"""
        system, user = _build_batch_prompt(batch, snippets)
        try:
            raw = self.provider.call_text(
                [Message(role="system", content=system), Message(role="user", content=user)],
                model=self.text_model,
                temperature=self.temperature,
                max_tokens=900,
            )
            data = parse_json_response(raw)
        except Exception as e:
            log.warning("C3 batch %d LLM 失败: %s", batch_idx, e)
            return [], str(e)

        if not data:
            return [], "LLM 返回空"

        result = agent_result_from_llm_json(data, dimension=self.dimension, max_score=12)
        return result.findings, None

    @staticmethod
    def _derive_from_findings(findings: list) -> tuple[str, int, int]:
        """从所有 batch 的 findings 汇总 verdict 和 score。

        策略：
        - 有 high → fail, score=4
        - 有 medium → partial, score=8
        - 全 low 或 pass → partial, score=10（低严重量多说明有普遍性问题）
        - 无 findings → pass, score=12
        """
        if not findings:
            return "pass", 12, 95

        high = sum(1 for f in findings if getattr(f, "severity", None) == "high")
        medium = sum(1 for f in findings if getattr(f, "severity", None) == "medium")
        low = sum(1 for f in findings if getattr(f, "severity", None) == "low")
        total = len(findings)

        if high > 0:
            return "fail", 4, 90
        if medium > 0:
            # medium 越多置信度越高（有明确问题）
            conf = min(90, 75 + medium * 2)
            return "partial", 8, conf
        if low > 0:
            # 全 low 说明整体通顺但可能有少量细节问题
            conf = min(85, 80 - low)  # low 太多反而降低置信
            return "partial", 10, conf
        return "pass", 12, 95