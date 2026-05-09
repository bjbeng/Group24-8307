"""Harness：Multi-Agent 审核框架。

六大模块：
- agent_group : DimSupervisor（2+1 架构）+ AuditOrchestrator
- tools       : @tool 工具注册表 + 检索/验证/抽取/技能工具
- guardrails  : 权限矩阵、输出 schema 验证、人工复核触发
- memory      : ContextBuilder（token 预算）+ SkillsStore
- hooks       : @hook 钩子系统（日志/验证/secret 扫描）
- session     : DocSession（断点续传）+ BatchJobManager
"""
from .agent_group.orchestrator import AuditOrchestrator
from .agent_group.dim_supervisor import DimSupervisor
from .memory.skills_store import SkillsStore

__all__ = ["AuditOrchestrator", "DimSupervisor", "SkillsStore"]
