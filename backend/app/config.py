from __future__ import annotations
from pathlib import Path
from typing import Any
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Web 应用安全配置 ──────────────────────────────────────────────────────
    secret_key: str
    database_url: str = "sqlite:///./data/audit.db"
    cors_origins: str = "http://localhost:5173"      # 逗号分隔
    upload_dir: Path = Path("./data/uploads")
    max_upload_mb: int = 50
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    cookie_httponly: bool = True
    engine_db_path: str = "./data/audit.db"

    # ── 全局开关 ─────────────────────────────────────────────────────────────
    llm_use_mock: bool = True           # True=Mock 模式，不调真实 API

    # ── 场景一（作业指导书文本审核）──────────────────────────────────────────
    # Explorer A = DeepSeek
    s1_explorer_a_base_url: str = "https://api.deepseek.com/v1"
    s1_explorer_a_api_key: str = "EMPTY"
    s1_explorer_a_model: str = "deepseek-chat"

    # Explorer B = Qwen
    s1_explorer_b_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    s1_explorer_b_api_key: str = "EMPTY"
    s1_explorer_b_model: str = "qwen-plus"

    # ── 场景二（高后果区风险管控，多模态）────────────────────────────────────
    # Explorer A = Qwen
    s2_explorer_a_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    s2_explorer_a_api_key: str = "EMPTY"
    s2_explorer_a_model: str = "qwen-plus"

    # Explorer B = Gemini（支持视觉）
    s2_explorer_b_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    s2_explorer_b_api_key: str = "EMPTY"
    s2_explorer_b_model: str = "gemini-1.5-flash"

    # ── 场景一 Critic ─────────────────────────────────────────────────────────
    s1_critic_base_url: str = "https://api.deepseek.com/v1"
    s1_critic_api_key: str = "EMPTY"
    s1_critic_model: str = "deepseek-reasoner"

    # ── 场景二 Critic ─────────────────────────────────────────────────────────
    s2_critic_base_url: str = "https://api.deepseek.com/v1"
    s2_critic_api_key: str = "EMPTY"
    s2_critic_model: str = "deepseek-reasoner"

    # ── Monitor Agent（独立轻量 LLM）────────────────────────────────────────
    monitor_base_url: str = "https://yunwu.ai/v1"
    monitor_api_key: str = "EMPTY"
    monitor_model: str = "deepseek-v3.2"
    monitor_interval_sec: int = 20

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def check_secret_key(self) -> "Settings":
        if len(self.secret_key) < 32:
            raise ValueError(
                f"SECRET_KEY 长度 {len(self.secret_key)} < 32，拒绝启动。"
            )
        return self

    @model_validator(mode="after")
    def check_cors_prod(self) -> "Settings":
        if self.cookie_secure and "*" in self.cors_origins_list:
            raise ValueError("生产模式下 CORS_ORIGINS 不允许包含 '*'")
        return self

    def build_engine_llm_config(self, scenario: str = "s1") -> dict[str, Any]:
        """
        根据场景构建审核引擎的 llm 配置块。

        场景一（s1）：A=DeepSeek, B=Qwen, Critic=DeepSeek Reasoner
        场景二（s2）：A=Qwen,     B=Gemini, Critic=DeepSeek Reasoner, Vision=Gemini
        """
        if self.llm_use_mock:
            return {
                "provider": "mock",
                "mock": {
                    "text_response": '{"verdict":"partial","score":8,"confidence":72,"details":"Mock审核","findings":[]}',
                    "vision_response": '{"confidence":0.8}',
                },
            }

        s = scenario.lower()
        a_url  = self.s1_explorer_a_base_url if s == "s1" else self.s2_explorer_a_base_url
        a_key  = self.s1_explorer_a_api_key  if s == "s1" else self.s2_explorer_a_api_key
        a_model= self.s1_explorer_a_model    if s == "s1" else self.s2_explorer_a_model
        b_url  = self.s1_explorer_b_base_url if s == "s1" else self.s2_explorer_b_base_url
        b_key  = self.s1_explorer_b_api_key  if s == "s1" else self.s2_explorer_b_api_key
        b_model= self.s1_explorer_b_model    if s == "s1" else self.s2_explorer_b_model

        critic_url   = self.s1_critic_base_url if s == "s1" else self.s2_critic_base_url
        critic_key   = self.s1_critic_api_key  if s == "s1" else self.s2_critic_api_key
        critic_model = self.s1_critic_model     if s == "s1" else self.s2_critic_model

        return {
            "provider": "api",
            # 全局 fallback：C2/C3/E1/E2/L2 单 Agent 用 build_provider() 时走这里
            "api": {
                "base_url":    a_url,
                "api_key":     a_key,
                "timeout":     120,
                "max_retries": 2,
            },
            # audit pipeline / orchestrator 读取的 text_model / vision_model
            "text_model":   a_model,
            "vision_model": b_model,
            # 角色专属
            "explorer_a": {
                "base_url": a_url, "api_key": a_key, "model": a_model,
                "temperature": 0.2,
            },
            "explorer_b": {
                "base_url": b_url, "api_key": b_key, "model": b_model,
                "temperature": 0.0,
            },
            "critic": {
                "base_url": critic_url, "api_key": critic_key, "model": critic_model,
            },
            "vision": {
                "base_url": b_url, "api_key": b_key, "model": b_model,
            },
        }


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
