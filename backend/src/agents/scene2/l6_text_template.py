"""L6 文字模板一致 —— 三大块描述与模板的一致性（rule_then_llm）。

三大块：
- 管道本体管控措施
- 外部环境风险管控
- 事故状态下前期处置

策略：
1. 规则：检查三大块标题/关键词在文档中是否存在
2. LLM：从 GB32167 / DB11_T2326 检索模板要点，与文档实际描述对比
"""

from __future__ import annotations

import logging
from typing import Any

from src.agents.base import AgentResult, BaseAgent, Finding, parse_json_response
from src.agents.llm_audit_utils import (
    agent_result_from_llm_json,
    build_json_only_system,
    format_snippets_for_prompt,
    retrieve_standard_snippets,
)
from src.llm import Message
from src.llm.provider import LLMProvider


log = logging.getLogger(__name__)

_DIM = "L6_text_template"


THREE_BLOCKS: dict[str, list[str]] = {
    "管道本体管控": ["管道本体", "本体管控", "本体管理", "本体保护"],
    "外部环境风险管控": ["外部环境", "外部风险", "环境风险管控", "周边环境管控",
                       "第三方损坏控制"],
    "事故状态下前期处置": ["事故状态", "前期处置", "事故处置", "应急处置"],
}


class L6TextTemplateAgent(BaseAgent):
    dimension = _DIM

    def __init__(
        self,
        provider: LLMProvider | None = None,
        text_model: str = "",
        *,
        repo: Any | None = None,
        temperature: float = 0.0,
    ) -> None:
        super().__init__(provider, text_model, temperature=temperature)
        self.repo = repo

    def run(self, chunks: list[dict[str, Any]]) -> AgentResult:
        full_text = "\n".join(
            (c.get("content") or "") for c in chunks if c.get("content")
        )
        if not full_text.strip():
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain", score=0, confidence=15,
                details="无文本可审。", need_human_review=True,
            )

        # 1. 规则阶段：三大块是否存在
        block_hits: dict[str, bool] = {}
        block_snippets: dict[str, str] = {}
        for block, keywords in THREE_BLOCKS.items():
            hit_kw = next((kw for kw in keywords if kw in full_text), None)
            block_hits[block] = bool(hit_kw)
            if hit_kw:
                idx = full_text.find(hit_kw)
                block_snippets[block] = full_text[idx: idx + 800]

        findings: list[Finding] = []
        for block, hit in block_hits.items():
            if not hit:
                findings.append(Finding(
                    severity="medium",
                    description=f"未找到三大块之[{block}]描述",
                    rule_id="L6.missing_block",
                ))

        if not any(block_hits.values()):
            return AgentResult(
                dimension=self.dimension,
                verdict="fail", score=3, confidence=85,
                details="文档完全缺失三大块描述。",
                findings=findings, need_human_review=True,
                extra={"block_hits": block_hits},
            )

        # 2. LLM 阶段：与模板对比
        llm_data: dict[str, Any] = {}
        if self.provider and self.text_model:
            snippets = retrieve_standard_snippets(
                self.repo, _DIM, "管控措施 应急处置", top_k=4,
            )
            std_block = format_snippets_for_prompt(snippets) if snippets else "（无）"

            system = build_json_only_system(
                "你是高后果区方案文字模板审核员。"
                "依据 GB32167/DB11_T2326 模板，判断文档三大块描述（管道本体管控、"
                "外部环境风险管控、事故状态下前期处置）是否与模板要求一致或包含。"
                "仅模糊不清标 partial；明显缺失/错误标 fail。"
            )
            blocks_text = "\n\n".join(
                f"### {b}\n{(s or '（缺失）')[:1200]}"
                for b, s in block_snippets.items()
            )
            user = (
                "## 标准/模板摘要\n"
                f"{std_block}\n\n"
                "## 文档三大块实际内容\n"
                f"{blocks_text}\n"
            )
            try:
                raw = self.provider.call_text(
                    [Message(role="system", content=system),
                     Message(role="user", content=user)],
                    model=self.text_model,
                    temperature=self.temperature,
                    max_tokens=900,
                )
                llm_data = parse_json_response(raw) or {}
            except Exception as e:
                log.warning("L6 LLM 失败: %s", e)

        if llm_data:
            result = agent_result_from_llm_json(
                llm_data, dimension=self.dimension, max_score=12,
            )
            # 合并规则 findings
            result.findings = findings + result.findings
            ex = dict(result.extra) if result.extra else {}
            ex["block_hits"] = block_hits
            result.extra = ex
            return result

        # LLM 未给结论时，仅按规则判定
        coverage = sum(1 for v in block_hits.values() if v) / len(block_hits)
        if coverage == 1.0:
            verdict, score, conf = "pass", 10, 75
        elif coverage >= 0.66:
            verdict, score, conf = "partial", 7, 70
        else:
            verdict, score, conf = "fail", 4, 75

        return AgentResult(
            dimension=self.dimension,
            verdict=verdict, score=score, confidence=conf,
            findings=findings,
            details=f"三大块覆盖率 {coverage:.0%}（仅规则判定）",
            extra={"block_hits": block_hits, "llm_skipped": True},
        )
