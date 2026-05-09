"""工具注册表与执行器。"""
from __future__ import annotations
import functools
import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)

@dataclass
class ToolDef:
    name: str
    fn: Callable
    description: str
    param_schema: dict[str, Any] = field(default_factory=dict)

_GLOBAL_REGISTRY: dict[str, ToolDef] = {}

def tool(name: str, description: str = ""):
    """注册为可调用工具的装饰器。"""
    def decorator(fn: Callable) -> Callable:
        desc = description or (fn.__doc__ or "").strip().split("\n")[0]
        sig = inspect.signature(fn)
        schema = {
            p: {"type": str(a.annotation), "default": a.default}
            for p, a in sig.parameters.items()
            if p != "self"
        }
        _GLOBAL_REGISTRY[name] = ToolDef(name=name, fn=fn, description=desc, param_schema=schema)
        fn._tool_name = name
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        wrapper._tool_name = name
        return wrapper
    return decorator

class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = dict(_GLOBAL_REGISTRY)

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def list_names(self) -> list[str]:
        return list(self._tools.keys())

class ToolExecutor:
    """检查权限后执行工具，记录调用日志。"""
    def __init__(
        self,
        registry: ToolRegistry,
        permissions: dict[str, list[str]],  # role -> [tool_name]
        hooks_pre: list[Callable] | None = None,
        hooks_post: list[Callable] | None = None,
    ) -> None:
        self._reg = registry
        self._perms = permissions
        self._hooks_pre = hooks_pre or []
        self._hooks_post = hooks_post or []

    def call(self, role: str, tool_name: str, **kwargs: Any) -> Any:
        allowed = self._perms.get(role, [])
        if tool_name not in allowed:
            raise PermissionError(f"角色 [{role}] 无权调用工具 [{tool_name}]")
        td = self._reg.get(tool_name)
        if td is None:
            raise KeyError(f"工具 [{tool_name}] 未注册")
        for h in self._hooks_pre:
            try:
                kwargs = h(tool_name, kwargs) or kwargs
            except Exception as e:
                log.warning("pre_tool hook 失败: %s", e)
        log.debug("tool_call role=%s name=%s params=%s", role, tool_name, list(kwargs.keys()))
        result = td.fn(**kwargs)
        for h in self._hooks_post:
            try:
                result = h(tool_name, result) or result
            except Exception as e:
                log.warning("post_tool hook 失败: %s", e)
        return result
