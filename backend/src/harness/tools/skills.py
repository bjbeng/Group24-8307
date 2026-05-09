"""技能类工具：搜索和保存 Hermes 风格的可复用审核技能。"""
from __future__ import annotations
from typing import Any, TYPE_CHECKING
from .registry import tool
if TYPE_CHECKING:
    from src.harness.memory.skills_store import SkillsStore

_store: "SkillsStore | None" = None

def set_skills_store(store: "SkillsStore") -> None:
    global _store
    _store = store

def _get_store() -> "SkillsStore":
    if _store is None:
        raise RuntimeError("SkillsStore 未初始化")
    return _store

@tool("search_skills", "搜索已沉淀的审核技能库")
def search_skills(query: str, dimension: str | None = None, top_k: int = 3) -> list[dict[str, Any]]:
    return _get_store().search(query, dimension=dimension, top_k=top_k)

@tool("save_skill", "Critic 固化高难度 case 的推理过程为可复用技能")
def save_skill(
    name: str,
    dimension: str,
    pattern: str,
    solution: str,
    example_in: str = "",
    example_out: str = "",
    tags: list[str] | None = None,
) -> str:
    skill_id = _get_store().save(
        name=name,
        dimension=dimension,
        pattern=pattern,
        solution=solution,
        example_in=example_in,
        example_out=example_out,
        tags=tags or [],
    )
    return skill_id
