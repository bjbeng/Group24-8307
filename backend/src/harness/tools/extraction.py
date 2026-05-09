"""抽取类工具：数字抽取、图片分类与分析。"""
from __future__ import annotations
import re
from typing import Any, TYPE_CHECKING
from .registry import tool
if TYPE_CHECKING:
    from src.llm.provider import LLMProvider

_provider: "LLMProvider | None" = None
_vision_model: str = ""

def set_provider(provider: "LLMProvider", vision_model: str = "") -> None:
    global _provider, _vision_model
    _provider = provider
    _vision_model = vision_model

# 数字抽取正则（带单位上下文）
_NUM_PATTERNS = [
    (re.compile(r"总.*?员工.*?(\d+)\s*人"), "total_staff"),
    (re.compile(r"员工.*?总数.*?(\d+)\s*人"), "total_staff"),
    (re.compile(r"共.*?(\d+)\s*人"), "total_staff"),
    (re.compile(r"管道.*?总长.*?(\d+(?:\.\d+)?)\s*(?:公里|km|KM)"), "pipeline_km"),
    (re.compile(r"管辖.*?(\d+(?:\.\d+)?)\s*(?:公里|km|KM)"), "pipeline_km"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:公里|km|KM).*?管道"), "pipeline_km"),
    (re.compile(r"工程师.*?(\d+)\s*人"), "engineers"),
    (re.compile(r"安全工程师.*?(\d+)\s*名"), "safety_engineers"),
    (re.compile(r"巡线工.*?(\d+)\s*(?:人|名)"), "patrol_workers"),
    (re.compile(r"区段长.*?(\d+)\s*(?:人|名)"), "section_managers"),
]

@tool("extract_numbers", "从文本里抽取数字+单位+上下文")
def extract_numbers(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for pat, key in _NUM_PATTERNS:
        m = pat.search(text)
        if m and key not in result:
            try:
                result[key] = float(m.group(1))
            except ValueError:
                result[key] = m.group(1)
    # 通用数字+单位扫描（补充）
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(公里|km|KM|人|名|条|段|个)", text):
        key = f"num_{m.group(2)}"
        if key not in result:
            result.setdefault(f"misc_{key}", []).append(float(m.group(1)))  # type: ignore[arg-type]
    return result

@tool("classify_image_type", "用轻量 VL 模型判断图片类型")
def classify_image_type(image_path: str) -> str:
    if _provider is None:
        return "unknown"
    from src.llm import Message
    prompt = (
        "判断这张图片的类型，只输出以下之一（英文）：\n"
        "evacuation_route / entry_route / approval / assembly_point / hca_aerial / material_diagram / other\n"
        "只输出类型名称，不要解释。"
    )
    try:
        # LLMProvider.call_vision(image_path, prompt, model, ...)
        result = _provider.call_vision(
            image_path=image_path,
            prompt=prompt,
            model=_vision_model,
        )
        result = result.strip().lower()
        valid = {"evacuation_route", "entry_route", "approval", "assembly_point",
                 "hca_aerial", "material_diagram", "other"}
        return result if result in valid else "other"
    except Exception:
        return "unknown"

@tool("analyze_image", "调用视觉模型对图片按 checklist 结构化分析")
def analyze_image(image_path: str, image_type: str, checklist: list[str] | None = None) -> dict[str, Any]:
    if _provider is None:
        return {"error": "VL provider 未初始化", "image_type": image_type}
    from src.agents.base import parse_json_response
    cl = checklist or _DEFAULT_CHECKLISTS.get(image_type, [])
    checklist_str = "\n".join(f"- {item}" for item in cl)
    prompt = (
        f"请分析这张【{image_type}】类型的图片，按以下检查项输出 JSON，"
        "每项值为 true/false/uncertain/描述字符串，另加 confidence(0-1)。\n"
        f"检查项：\n{checklist_str}\n"
        "只输出 JSON，不要围栏。"
    )
    try:
        raw = _provider.call_vision(
            image_path=image_path,
            prompt=prompt,
            model=_vision_model,
        )
        result = parse_json_response(raw)
        result["image_type"] = image_type
        return result
    except Exception as e:
        return {"error": str(e), "image_type": image_type}

_DEFAULT_CHECKLISTS: dict[str, list[str]] = {
    "evacuation_route": [
        "evacuates_both_sides（往两侧疏散，非顺管道方向）",
        "pipeline_marked（管道标注）",
        "three_parallel_lines（管道中心线+左右影响范围三条线）",
        "impact_radius_marked（潜在影响半径标注）",
        "assembly_points_count（集合点数量）",
        "legend_correct（图例正确）",
        "route_obstacles（穿越障碍：河流/山地/建筑物）",
    ],
    "entry_route": [
        "vehicle_accessible（适合车辆通行）",
        "road_width_adequate（道路宽度足够）",
        "crosses_obstacles（穿越障碍）",
        "distance_marked（距离标注）",
        "pipeline_marked（管道标注）",
    ],
    "approval": [
        "editor_signed（编制人签字）",
        "reviewer_signed（审核人签字）",
        "approver_signed（批准人签字）",
        "date_sequence_valid（编制日期 ≤ 审核日期 ≤ 批准日期）",
        "all_roles_present（三个角色齐全）",
    ],
    "hca_aerial": [
        "pipeline_visible（管道可见）",
        "building_attributes_complete（建筑物属性描述完整）",
        "impact_zone_marked（影响范围标注）",
        "scale_bar_present（比例尺存在）",
    ],
}
