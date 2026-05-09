"""LLMProvider 工厂：根据配置返回具体后端实例。

新增后端 = 在此添加分支。业务代码全部使用 `build_provider()` 拿 Provider，便于测试替换。
"""

from __future__ import annotations

import os
from typing import Any

from .api_provider import OpenAICompatibleProvider
from .mock_provider import MockProvider
from .provider import LLMProvider


def build_provider(config: dict[str, Any]) -> LLMProvider:
    """根据 `config['llm']` 字段构造默认 Provider。

    环境变量 LLM_BASE_URL / LLM_API_KEY 可覆盖 YAML 里的 api 配置，
    方便 CLI 直接通过 .env 切换服务商。
    """
    llm_cfg = config.get("llm", {})
    provider_kind = llm_cfg.get("provider", "api")

    if provider_kind == "mock":
        mock_cfg = llm_cfg.get("mock", {})
        return MockProvider(
            text_response=mock_cfg.get("text_response", ""),
            vision_response=mock_cfg.get("vision_response", ""),
            responses=mock_cfg.get("responses"),
        )

    if provider_kind == "api":
        api_cfg = llm_cfg.get("api", {})
        base_url = os.environ.get("LLM_BASE_URL") or api_cfg.get("base_url", "http://localhost:8000/v1")
        api_key = os.environ.get("LLM_API_KEY") or api_cfg.get("api_key", "EMPTY")
        return OpenAICompatibleProvider(
            base_url=base_url,
            api_key=api_key,
            timeout=api_cfg.get("timeout", 120.0),
            max_retries=api_cfg.get("max_retries", 2),
        )

    raise ValueError(f"未知的 LLM provider 类型: {provider_kind}")


def build_provider_for_role(config: dict[str, Any], role: str) -> LLMProvider:
    """
    为指定角色（explorer_a / explorer_b / critic / vision）构建 Provider。

    每个角色可以有独立的 base_url / api_key / provider 类型，
    支持跨服务商（DeepSeek / Qwen / Gemini / vLLM 等）混合使用。

    config 结构示例（default.yaml）：
      llm:
        explorer_a:
          provider: api
          base_url: https://api.deepseek.com/v1
          api_key: sk-xxx
        explorer_b:
          provider: api
          base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
          api_key: sk-yyy
        critic:
          provider: api
          base_url: https://api.deepseek.com/v1
          api_key: sk-xxx
        vision:
          provider: api
          base_url: https://generativelanguage.googleapis.com/v1beta
          api_key: AIza-zzz

    如果角色配置缺失，fallback 到全局 api 配置。
    """
    llm_cfg = config.get("llm", {})
    role_cfg = llm_cfg.get(role, {})          # 角色专属配置
    global_kind = llm_cfg.get("provider", "api")

    # mock 模式：全局 mock，不管角色
    if global_kind == "mock" or role_cfg.get("provider") == "mock":
        mock_cfg = llm_cfg.get("mock", {})
        return MockProvider(
            text_response=mock_cfg.get("text_response", ""),
            vision_response=mock_cfg.get("vision_response", ""),
            responses=mock_cfg.get("responses"),
        )

    # 角色有独立 API 配置
    if role_cfg:
        global_api = llm_cfg.get("api", {})
        return OpenAICompatibleProvider(
            base_url=role_cfg.get("base_url", global_api.get("base_url", "http://localhost:8000/v1")),
            api_key=role_cfg.get("api_key", global_api.get("api_key", "EMPTY")),
            timeout=float(role_cfg.get("timeout", global_api.get("timeout", 120.0))),
            max_retries=int(role_cfg.get("max_retries", global_api.get("max_retries", 2))),
        )

    # fallback：用全局配置
    return build_provider(config)
