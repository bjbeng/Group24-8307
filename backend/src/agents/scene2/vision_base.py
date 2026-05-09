"""场景二图片维度 Agent 基类。

设计要点：
- 与 BaseAgent 同构，但 ``run`` 接收 image_chunks（dict 列表）而非 text chunks
- 子类声明 ``image_types``：本维度只看哪些类型（避免无关图片送入 VL）
- 提供 ``_call_vision_json`` 通用工具：调 VL → 抓 JSON → 兜底
- pipeline 端通过 ``isinstance(agent, VisionAgent)`` 路由不同输入
"""

from __future__ import annotations

import logging
from typing import Any

from src.agents.base import AgentResult, BaseAgent, parse_json_response
from src.llm.provider import LLMProvider


log = logging.getLogger(__name__)


class VisionAgent(BaseAgent):
    """图片维度 Agent 基类。"""

    dimension: str = ""
    image_types: tuple[str, ...] = ()

    def __init__(
        self,
        provider: LLMProvider,
        vision_model: str,
        *,
        repo: Any | None = None,
        temperature: float = 0.0,
    ) -> None:
        super().__init__(provider, vision_model, temperature=temperature)
        self.vision_model = vision_model
        self.repo = repo

    def run(self, image_chunks: list[dict[str, Any]]) -> AgentResult:
        """筛选相关 image_type，转交 ``analyze``。"""
        relevant = [
            img for img in image_chunks
            if img.get("image_type") in self.image_types
        ]
        if not relevant:
            type_str = "/".join(self.image_types)
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                score=0,
                confidence=15,
                details=f"未找到 {type_str} 类型的图片，无法审核。",
                need_human_review=True,
            )
        try:
            return self.analyze(relevant)
        except Exception as e:
            log.exception("%s analyze 异常", self.dimension)
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                score=0,
                confidence=10,
                details=f"VL agent 执行异常：{e}",
                need_human_review=True,
            )

    def analyze(self, images: list[dict[str, Any]]) -> AgentResult:
        """子类必须实现：基于已筛选的 images 列表产出结论。"""
        raise NotImplementedError

    # ------------------------------------------------------------------
    def _call_vision_json(
        self,
        image_path: str,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1200,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """调一次 VL 模型，解析返回的 JSON；失败返回 {}。"""
        if not image_path:
            return {}
        try:
            raw = self.provider.call_vision(
                image_path=image_path,
                prompt=prompt,
                model=self.vision_model,
                temperature=self.temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                system=system,
            )
        except Exception as e:
            log.warning("VL 调用失败 (%s): %s", image_path, e)
            return {}
        return parse_json_response(raw) or {}
