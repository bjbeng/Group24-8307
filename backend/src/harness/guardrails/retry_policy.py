"""Agent 调用重试与 fallback 策略。"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

log = logging.getLogger(__name__)
T = TypeVar("T")

@dataclass
class AgentCallPolicy:
    max_retries: int = 2
    backoff_seconds: float = 1.0
    max_tool_calls_per_session: int = 15
    fallback_on_parse_error: bool = True
    fallback_on_timeout: bool = True
    fallback_on_permission_error: bool = False  # 权限违规不重试，立即失败

def with_retry(
    fn: Callable[[], T],
    policy: AgentCallPolicy,
    fallback_fn: Callable[[], T] | None = None,
    context_label: str = "",
) -> T:
    last_exc: Exception | None = None
    for attempt in range(policy.max_retries + 1):
        try:
            return fn()
        except PermissionError:
            if not policy.fallback_on_permission_error:
                raise
            log.error("权限违规 [%s]，不重试", context_label)
            break
        except (ValueError, KeyError) as e:
            if not policy.fallback_on_parse_error:
                raise
            last_exc = e
            log.warning("[%s] 解析错误第 %d 次: %s", context_label, attempt + 1, e)
        except TimeoutError as e:
            if not policy.fallback_on_timeout:
                raise
            last_exc = e
            log.warning("[%s] 超时第 %d 次", context_label, attempt + 1)
        except Exception as e:
            last_exc = e
            log.warning("[%s] 异常第 %d 次: %s", context_label, attempt + 1, e)
        if attempt < policy.max_retries:
            time.sleep(policy.backoff_seconds * (attempt + 1))
    if fallback_fn is not None:
        log.warning("[%s] 全部重试失败，使用 fallback", context_label)
        return fallback_fn()
    raise RuntimeError(f"[{context_label}] 全部重试失败") from last_exc
