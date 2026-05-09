"""场景二旧版 I1-I6 视觉 Agent（对齐 qzq_addwork2 流程）。"""
from __future__ import annotations

import logging
from typing import Any

from src.agents.base import AgentResult, Finding, parse_json_response
from src.llm.provider import LLMProvider

log = logging.getLogger(__name__)


class BaseImageAgent:
    """视觉 Agent 基类。"""

    dimension: str = ""
    checklist: list[str] = []

    def __init__(self, provider: LLMProvider, vision_model: str) -> None:
        self._provider = provider
        self._vision_model = vision_model

    def run(self, image_paths: list[str]) -> AgentResult:
        if not image_paths:
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                confidence=0,
                details="无对应图片",
                need_human_review=True,
            )

        all_findings: list[Finding] = []
        total_conf = 0
        analyzed = 0

        for path in image_paths:
            try:
                data = self._analyze_image(path)
                conf = int(float(data.pop("confidence", 0.7)) * 100)
                total_conf += conf
                analyzed += 1
                findings = self._extract_findings(data, path)
                all_findings.extend(findings)
            except Exception as e:
                log.warning("[%s] 分析失败 %s: %s", self.dimension, path, e)

        if not analyzed:
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                confidence=10,
                details="全部图片分析失败",
                need_human_review=True,
            )

        avg_conf = total_conf // analyzed
        if not all_findings:
            verdict, score = "pass", 12
        elif avg_conf >= 70:
            verdict, score = "partial", max(4, 12 - len(all_findings) * 2)
        else:
            verdict, score = "fail", max(0, 12 - len(all_findings) * 3)

        return AgentResult(
            dimension=self.dimension,
            verdict=verdict,
            score=score,
            confidence=avg_conf,
            findings=all_findings,
            details=f"分析 {analyzed} 张图，发现 {len(all_findings)} 个问题",
            need_human_review=avg_conf < 60 or verdict == "fail",
            extra={"analyzed_count": analyzed, "image_type": self.dimension},
        )

    def _analyze_image(self, path: str) -> dict[str, Any]:
        checklist_str = "\n".join(f"- {item}" for item in self.checklist)
        prompt = (
            f"分析这张【{self.dimension}】类型的图片，"
            "按以下检查项输出 JSON，每项值为 true/false/uncertain/描述字符串，"
            f"另加 confidence(0.0-1.0)：\n{checklist_str}\n只输出 JSON，不要围栏。"
        )
        raw = self._provider.call_vision(
            image_path=path,
            prompt=prompt,
            model=self._vision_model,
        )
        return parse_json_response(raw) or {}

    def _extract_findings(self, data: dict[str, Any], path: str) -> list[Finding]:
        findings = []
        for key, val in data.items():
            if key in ("confidence", "image_type"):
                continue
            is_issue = (
                val is False
                or (isinstance(val, str) and "uncertain" in val.lower())
                or (isinstance(val, str) and "否" in val)
                or (isinstance(val, str) and "不符" in val)
                or (isinstance(val, str) and "缺失" in val)
            )
            if is_issue:
                findings.append(
                    Finding(
                        severity="high" if "三条" in key or "方向" in key or "签字" in key else "medium",
                        description=f"{key}：{val}",
                        evidence=f"图片路径：{path}",
                    )
                )
        return findings


class I1EvacuationRouteAgent(BaseImageAgent):
    dimension = "I1_evacuation_route"
    checklist = [
        "evacuates_both_sides（路线是否往两侧疏散，非顺管道方向）",
        "three_parallel_lines（是否有三条平行线：管道中心线+左右影响范围）",
        "impact_radius_marked（潜在影响半径是否标注）",
        "pipeline_marked（管道是否标注）",
        "assembly_points_present（紧急集合点是否标注）",
        "obstacles_noted（是否标注穿越障碍：河流/山地/建筑物）",
        "legend_complete（图例是否完整）",
        "north_arrow（是否有指北针）",
        "scale_bar（是否有比例尺）",
    ]


class I2AssemblyPointAgent(BaseImageAgent):
    dimension = "I2_assembly_point"
    checklist = [
        "both_sides_assembly（是否在管道两侧各有集合点）",
        "safe_distance_marked（距管道安全距离是否标注）",
        "accessible_by_foot（步行可达性是否合理）",
        "clear_labeling（集合点标注是否清晰）",
        "wind_direction_considered（是否考虑风向，集合点在上风方向）",
    ]


class I3MaterialAgent(BaseImageAgent):
    dimension = "I3_material"
    checklist = [
        "fire_extinguisher_listed（灭火器/消防设备是否列出）",
        "protective_gear_listed（个人防护装备是否列出）",
        "detection_equipment_listed（气体探测仪是否列出）",
        "first_aid_listed（急救设备是否列出）",
        "quantity_specified（各类物资数量是否标注）",
        "storage_location_marked（存放位置是否标注）",
        "responsible_person_listed（责任人是否标注）",
    ]


class I4EntryRouteAgent(BaseImageAgent):
    dimension = "I4_entry_route"
    checklist = [
        "vehicle_accessible（路线是否适合应急车辆通行）",
        "road_width_adequate（道路宽度是否足够大型车辆）",
        "obstacles_marked（穿越障碍：山地/河流/狭窄路段是否标注）",
        "distance_marked（行车距离/时间是否标注）",
        "pipeline_location_marked（管道位置是否标注）",
        "alternative_route（是否有备用进场路线）",
        "gate_access_noted（是否标注门禁/进入方式）",
    ]


class I5HCAAerialAgent(BaseImageAgent):
    dimension = "I5_hca_aerial"
    checklist = [
        "pipeline_visible（管道走向是否可见/标注）",
        "impact_zone_marked（高后果区影响范围是否标注）",
        "building_types_identified（周边建筑类型是否识别：居民楼/学校/医院等）",
        "building_distance_marked（建筑物距管道距离是否标注）",
        "scale_bar_present（比例尺是否存在）",
        "north_arrow_present（指北针是否存在）",
        "sensitive_targets_highlighted（敏感目标是否突出显示）",
        "population_density_noted（人口密集区是否标注）",
    ]


class I6ApprovalPageAgent(BaseImageAgent):
    """专项：手写日期识别 + 签字完整性。"""

    dimension = "I6_approval_page"
    checklist = [
        "editor_signed（编制人是否签字）",
        "editor_date（编制日期，格式：YYYY-MM-DD 或 YYYY年MM月DD日）",
        "reviewer_signed（审核人是否签字）",
        "reviewer_date（审核日期）",
        "approver_signed（批准人是否签字）",
        "approver_date（批准日期）",
        "date_sequence_valid（日期顺序是否正确：编制 ≤ 审核 ≤ 批准）",
        "all_positions_filled（三个职位栏是否全部填写）",
        "company_seal（是否有公司盖章）",
    ]

    def _analyze_image(self, path: str) -> dict[str, Any]:
        prompt = (
            "这是一份审批签字扫描页，请仔细识别手写内容，输出 JSON：\n"
            "- editor_signed: true/false\n"
            "- editor_date: 识别到的日期字符串（如 '2025-03-15'），未识别到为 null\n"
            "- reviewer_signed: true/false\n"
            "- reviewer_date: 识别到的日期字符串\n"
            "- approver_signed: true/false\n"
            "- approver_date: 识别到的日期字符串\n"
            "- date_sequence_valid: true/false/uncertain（编制日期 ≤ 审核日期 ≤ 批准日期）\n"
            "- all_positions_filled: true/false\n"
            "- company_seal: true/false\n"
            "- confidence: 0.0-1.0（手写识别整体置信度）\n"
            "只输出 JSON，不要围栏。"
        )
        raw = self._provider.call_vision(
            image_path=path,
            prompt=prompt,
            model=self._vision_model,
        )
        data = parse_json_response(raw) or {}
        if data.get("date_sequence_valid") is None:
            data["date_sequence_valid"] = self._check_date_order(
                data.get("editor_date"),
                data.get("reviewer_date"),
                data.get("approver_date"),
            )
        return data

    @staticmethod
    def _check_date_order(ed: Any, rd: Any, ad: Any) -> str:
        import re as _re

        def parse_date(s: Any) -> str | None:
            if not s or not isinstance(s, str):
                return None
            m = _re.search(r"(\d{4})[年\-](\d{1,2})[月\-](\d{1,2})", s)
            if m:
                return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            return None

        dates = [parse_date(ed), parse_date(rd), parse_date(ad)]
        valid = [d for d in dates if d]
        if len(valid) < 2:
            return "uncertain"
        return "true" if sorted(valid) == valid else "false"
