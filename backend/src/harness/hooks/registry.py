"""钩子注册表：@hook 装饰器 + 事件分发。"""
from __future__ import annotations
import functools
import logging
from collections import defaultdict
from typing import Callable, Any

log = logging.getLogger(__name__)

_HOOK_EVENTS = (
    "pre_tool_call",
    "post_tool_call",
    "pre_agent_run",
    "post_agent_run",
    "pre_commit",
    "post_batch",
)

class HookRegistry:
    def __init__(self) -> None:
        self._hooks: dict[str, list[Callable]] = defaultdict(list)

    def register(self, event: str, fn: Callable) -> None:
        if event not in _HOOK_EVENTS:
            raise ValueError(f"未知 hook 事件: {event}，合法值: {_HOOK_EVENTS}")
        self._hooks[event].append(fn)

    def fire(self, event: str, *args: Any, **kwargs: Any) -> Any:
        """触发 event 下的所有钩子；最后一个钩子的返回值作为结果。"""
        result = None
        for fn in self._hooks.get(event, []):
            try:
                result = fn(*args, **kwargs) or result
            except Exception as e:
                log.warning("hook [%s] 执行异常: %s", fn.__name__, e)
        return result

_GLOBAL: HookRegistry = HookRegistry()

def get_global_registry() -> HookRegistry:
    return _GLOBAL

def hook(event: str):
    """把函数注册到全局 HookRegistry 的指定事件。"""
    def decorator(fn: Callable) -> Callable:
        _GLOBAL.register(event, fn)
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        return wrapper
    return decorator
