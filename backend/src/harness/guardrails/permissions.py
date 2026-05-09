"""工具权限矩阵：角色 → 允许调用的工具列表。"""
from __future__ import annotations
from dataclasses import dataclass, field

TOOL_PERMISSIONS: dict[str, list[str]] = {
    "explorer_a": [
        "fts_search",
        "get_chunks_by_dimension",
        "get_chunk_by_id",
        "get_appendix",
        "cross_ref_lookup",
        "search_chunks",
        "extract_numbers",
        "analyze_image",
        "classify_image_type",
        "add_finding",
    ],
    "explorer_b": [
        "fts_search",
        "get_chunks_by_dimension",
        "get_chunk_by_id",
        "get_appendix",
        "cross_ref_lookup",
        "search_chunks",
        "verify_standard_version",
        "extract_numbers",
        "analyze_image",
        "classify_image_type",
        "add_finding",
    ],
    "critic": [
        "verify_evidence_in_doc",
        "cross_ref_lookup",
        "compare_emergency_steps",
        "search_skills",
        "save_skill",
        "get_chunk_by_id",
        "add_finding",
        "add_docx_annotation",
    ],
    "orchestrator": [
        "get_chunks_by_dimension",
        "get_chunk_by_id",
        "search_chunks",
    ],
}

@dataclass
class ToolPermissionMatrix:
    permissions: dict[str, list[str]] = field(default_factory=lambda: dict(TOOL_PERMISSIONS))

    def check(self, role: str, tool_name: str) -> None:
        allowed = self.permissions.get(role, [])
        if tool_name not in allowed:
            raise PermissionError(f"角色 [{role}] 无权调用工具 [{tool_name}]，允许列表：{allowed}")

    def allowed_tools(self, role: str) -> list[str]:
        return list(self.permissions.get(role, []))
