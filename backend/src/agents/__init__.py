"""Agents 层：场景一在 scene1/，场景二在 scene2/。

顶层 __init__ 保留对场景一 Agent 的转发，
供 AuditPipeline / AuditOrchestrator 等旧代码直接 import。
"""
from .base import AgentResult, BaseAgent, Finding, parse_json_response
from .scene1 import (
    C1StructureAgent,
    C2ContentAgent,
    C3LanguageAgent,
    C4ReferenceAgent,
    C5LogicAgent,
    E1StaffingAgent,
    E2EmergencyAgent,
    L2StandardsAgent,
    explorers_agree,
    merge_explorer_b_to_final,
)

__all__ = [
    "AgentResult", "BaseAgent", "Finding", "parse_json_response",
    "C1StructureAgent", "C2ContentAgent", "C3LanguageAgent",
    "C4ReferenceAgent", "C5LogicAgent",
    "E1StaffingAgent", "E2EmergencyAgent",
    "L2StandardsAgent",
    "explorers_agree", "merge_explorer_b_to_final",
]
