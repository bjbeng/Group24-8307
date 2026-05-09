"""场景二图片维度的 VL Prompt 集中管理。

每个 image_type 对应：
- ``SYSTEM``：角色与任务说明
- ``USER``：JSON schema 与输出约束（统一只输出 JSON，不带围栏）
- ``DESC_PROMPT``：image_pipeline 预分析时让 VL 生成自然语言摘要 description
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# 通用：图片预分析时生成自然语言描述（FTS 检索用）
# ---------------------------------------------------------------------------

DESC_PROMPT = (
    "请用 1-2 句话客观描述图中可见内容（建筑、道路、管道、签字、文字标注等）。"
    "不要解释、不要润色、不要主观判断。直接输出描述文本。"
)


# ---------------------------------------------------------------------------
# image_type → 结构化分析 Prompt
# ---------------------------------------------------------------------------

PROMPTS: dict[str, dict[str, str]] = {
    # --- I1：签字审批页 ---
    "approval": {
        "system": (
            "你是文档审批页识别专家。给定一张签字审批页图像，"
            "需识别其中所有手写签名、对应角色和日期。"
        ),
        "user": (
            "识别图中的签名、角色和日期，输出 JSON：\n"
            "{\n"
            '  "signatures": [\n'
            '    {"role": "编制|校对|审核|批准|评审组长", "name_present": true/false,'
            ' "name_text": "若可识别填手写文字，否则空", '
            ' "date": "YYYY-MM-DD 或空", "date_format_valid": true/false}\n'
            "  ],\n"
            '  "all_required_signed": true/false,\n'
            '  "date_sequence_valid": true/false,\n'
            '  "remark": "评审/签发意见摘要，可空"\n'
            "}\n"
            "只输出一个 JSON 对象，不要 markdown 围栏。"
        ),
    },

    # --- I3：高后果区影像图 ---
    "hca_aerial": {
        "system": (
            "你是油气管道高后果区影像图审核员。需识别图中是否标注了管道、"
            "潜在影响半径、周边建筑物属性。"
        ),
        "user": (
            "识别图中要素并输出 JSON：\n"
            "{\n"
            '  "pipeline_visible": true/false,\n'
            '  "pipeline_solid_line": true/false,\n'
            '  "impact_radius_dashed": true/false,\n'
            '  "three_parallel_lines": true/false,\n'
            '  "buildings": [\n'
            '    {"label": "如龙涧村/学校", "distance_marked": true/false,'
            ' "people_count_marked": true/false}\n'
            "  ],\n"
            '  "legend_present": true/false,\n'
            '  "scale_bar_present": true/false,\n'
            '  "remark": "整体一句话评价"\n'
            "}\n"
            "只输出 JSON，不要围栏。"
        ),
    },

    # --- I4：入场线路图 ---
    "entry_route": {
        "system": (
            "你是应急救援入场线路审核员。需识别图中入场路线是否合理（不穿山、"
            "不穿墙、不无桥跨河、不穿建筑物、在可行车道上）。"
        ),
        "user": (
            "识别入场线路要素并输出 JSON：\n"
            "{\n"
            '  "route_marked": true/false,\n'
            '  "vehicle_accessible": true/false,\n'
            '  "crosses_obstacles": ["山地","河流","建筑物","其他"或空数组],\n'
            '  "no_bridge_river_crossing": true/false,\n'
            '  "text_description_present": true/false,\n'
            '  "remark": "对入场线路合理性的一句话评价"\n'
            "}\n"
            "只输出 JSON，不要围栏。"
        ),
    },

    # --- I5：逃生路线 / 集结点 ---
    "evacuation_route": {
        "system": (
            "你是应急疏散逃生路线审核员。需识别图中疏散方向是否标注、"
            "方向是否向管道两侧（不应顺管道方向逃生）。"
        ),
        "user": (
            "识别逃生路线要素并输出 JSON：\n"
            "{\n"
            '  "evacuation_arrows_present": true/false,\n'
            '  "evacuates_to_both_sides": true/false,\n'
            '  "follows_pipeline_direction": true/false,\n'
            '  "pipeline_marked": true/false,\n'
            '  "remark": "对疏散方向合理性的一句话评价"\n'
            "}\n"
            "只输出 JSON，不要围栏。"
        ),
    },
    "assembly_point": {
        "system": (
            "你是应急疏散集结点审核员。需识别图中标注的集结点位置和数量，"
            "以及是否在潜在影响半径范围之外。"
        ),
        "user": (
            "识别集结点要素并输出 JSON：\n"
            "{\n"
            '  "assembly_points_count": 0,\n'
            '  "labels": ["如应急疏散集结点 A"],\n'
            '  "outside_impact_radius": true/false,\n'
            '  "impact_radius_visible": true/false,\n'
            '  "remark": "一句话评价"\n'
            "}\n"
            "只输出 JSON，不要围栏。"
        ),
    },

    # --- I6：水体敏感图 ---
    "water_containment": {
        "system": (
            "你是水体敏感型高后果区围油设施审核员。需识别图中围油栏、"
            "拦油设施位置标注是否合理。"
        ),
        "user": (
            "识别围油设施要素并输出 JSON：\n"
            "{\n"
            '  "water_body_visible": true/false,\n'
            '  "containment_facility_marked": true/false,\n'
            '  "facility_position_appropriate": true/false,\n'
            '  "facility_types": ["围油栏","拦油坝","其他"],\n'
            '  "remark": "一句话评价"\n'
            "}\n"
            "只输出 JSON，不要围栏。"
        ),
    },

    # --- I7：市政管网交叉图 ---
    "municipal_crossing": {
        "system": (
            "你是市政管网交叉位置审核员。需识别图中油气管道与市政设施"
            "（铁路/公路/电力/通信等）的交叉位置标注是否清晰。"
        ),
        "user": (
            "识别交叉要素并输出 JSON：\n"
            "{\n"
            '  "crossing_marked": true/false,\n'
            '  "crossing_count": 0,\n'
            '  "crossing_types": ["铁路","公路","电缆","其他"],\n'
            '  "depth_marked": true/false,\n'
            '  "text_description_present": true/false,\n'
            '  "remark": "一句话评价"\n'
            "}\n"
            "只输出 JSON，不要围栏。"
        ),
    },

    # --- 现场图、入场物资点 ---
    "emergency_assets": {
        "system": "你识别图中应急物资存放点位置。",
        "user": (
            "识别物资点要素并输出 JSON：\n"
            "{\n"
            '  "asset_points_count": 0,\n'
            '  "labels": ["如洛阳作业区应急仓库"],\n'
            '  "remark": "一句话"\n'
            "}\n"
            "只输出 JSON，不要围栏。"
        ),
    },
    "site_photo": {
        "system": "你识别管道现场实景图中的关键标识。",
        "user": (
            "识别现场图要素并输出 JSON：\n"
            "{\n"
            '  "pipeline_marker_present": true/false,\n'
            '  "warning_sign_present": true/false,\n'
            '  "scene_description": "如管道路标牌+铁路+树林",\n'
            '  "remark": "一句话"\n'
            "}\n"
            "只输出 JSON，不要围栏。"
        ),
    },
}


def get_analysis_prompt(image_type: str) -> tuple[str, str] | None:
    """返回 (system, user) prompt；未注册的类型返回 None。"""
    if image_type not in PROMPTS:
        return None
    p = PROMPTS[image_type]
    return p["system"], p["user"]
