"""I8 图文一致性 —— rule_then_llm 双输入维度。

输入：text chunks + image_chunks（hca_aerial）
流程：
1. 规则阶段：从 text chunks 抽取"高后果区基本信息/特征描述/周边建筑"段落
2. LLM 阶段：把文字 + 图片 analysis 一并送给文本 LLM，对比建筑物数量/类型一致性
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.agents.base import AgentResult, BaseAgent, Finding, parse_json_response
from src.agents.llm_audit_utils import (
    agent_result_from_llm_json,
    build_json_only_system,
)
from src.llm import Message
from src.llm.provider import LLMProvider


log = logging.getLogger(__name__)

_DIM = "I8_image_text_consistency"

# 描述高后果区特征的章节关键词
HCA_DESC_KEYWORDS = (
    "高后果区基本信息", "高后果区特征", "周边建筑", "周边环境",
    "防护目标", "影响半径", "管道周边", "建筑物分布",
)


class I8ImageTextConsistencyAgent(BaseAgent):
    dimension = _DIM

    def __init__(
        self,
        provider: LLMProvider,
        text_model: str,
        *,
        repo: Any | None = None,
        temperature: float = 0.0,
    ) -> None:
        super().__init__(provider, text_model, temperature=temperature)
        self.repo = repo

    def run(
        self,
        chunks: list[dict[str, Any]],
        image_chunks: list[dict[str, Any]] | None = None,
    ) -> AgentResult:
        image_chunks = image_chunks or []

        # 1) 规则阶段：抽取 hca_aerial 图分析结果
        aerial_imgs = [img for img in image_chunks
                       if img.get("image_type") == "hca_aerial"]
        if not aerial_imgs:
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain", score=0, confidence=15,
                details="未找到高后果区影像图，无法做图文一致性比对。",
                need_human_review=True,
            )

        # 2) 抽取文档中"高后果区特征描述"段落
        hca_text = self._extract_hca_description(chunks)
        if not hca_text.strip():
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain", score=0, confidence=20,
                details="文档中未找到高后果区特征/建筑描述段落。",
                need_human_review=True,
            )

        # 3) LLM 阶段：拼装上下文喂给文本 LLM
        aerial_summary = self._aerial_summary(aerial_imgs)
        system = build_json_only_system(
            "你是高后果区图文一致性审核员。"
            "对比文档中的高后果区描述与影像图标注（建筑物数量/类型/距离），"
            "判断两者是否一致。仅基于给定信息判断，不要臆测。"
        )
        user = (
            "## 文档中的高后果区描述\n"
            f"{hca_text[:3500]}\n\n"
            "## 影像图分析摘要（VL 输出）\n"
            f"{aerial_summary[:3000]}\n\n"
            "请判断两者是否一致；不一致项一一列入 findings。"
        )
        try:
            raw = self.provider.call_text(
                [Message(role="system", content=system),
                 Message(role="user", content=user)],
                model=self.text_model,
                temperature=self.temperature,
                max_tokens=1200,
            )
            data = parse_json_response(raw)
        except Exception as e:
            log.warning("I8 LLM 失败: %s", e)
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain", score=0, confidence=20,
                details=f"LLM 调用失败：{e}",
                need_human_review=True,
            )

        if not data:
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain", score=0, confidence=25,
                details="LLM 未返回可解析 JSON。",
                need_human_review=True,
            )

        result = agent_result_from_llm_json(data, dimension=self.dimension, max_score=12)
        result.extra = {
            **result.extra,
            "aerial_image_count": len(aerial_imgs),
            "hca_text_chars": len(hca_text),
        }
        return result

    # ------------------------------------------------------------------
    @staticmethod
    def _extract_hca_description(chunks: list[dict[str, Any]]) -> str:
        """按关键词命中拼接相关段落。"""
        parts: list[str] = []
        for c in chunks:
            text = (c.get("content") or "").strip()
            title = (c.get("title") or "").strip()
            if not text:
                continue
            if any(kw in text or kw in title for kw in HCA_DESC_KEYWORDS):
                parts.append(text)
        return "\n---\n".join(parts[:8])

    @staticmethod
    def _aerial_summary(images: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for i, img in enumerate(images, 1):
            a = img.get("analysis") or {}
            desc = img.get("description", "")
            buildings = a.get("buildings") or []
            lines.append(
                f"图{i} ({img.get('chunk_id', '')}):\n"
                f"  描述: {desc[:200]}\n"
                f"  建筑物: {json.dumps(buildings, ensure_ascii=False)[:500]}\n"
                f"  pipeline_visible={a.get('pipeline_visible')}, "
                f"impact_radius_dashed={a.get('impact_radius_dashed')}"
            )
        return "\n\n".join(lines)
