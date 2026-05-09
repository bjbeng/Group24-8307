"""SubAgent：单维度审核子智能体。

每个 SubAgent 封装一个现有的维度 agent，加上：
1. role 偏置（A=高召回 / B=高精度）
2. 统一调用接口
3. 场景路由（scenario="s1" 文本 / "s2" 多模态）

SubAgent 可以是：
- 纯规则（C1/C4）
- FTS + LLM（C2/C3/E2/L2）
- 公式 + LLM/regex（E1）
- LangGraph（C5）
- 视觉模型（场景二 I1-I8）
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Literal

from src.agents.base import AgentResult

log = logging.getLogger(__name__)

Role = Literal["a", "b", "audit"]   # audit = 单 Explorer 审核阶段
Scenario = Literal["s1", "s2"]      # s1=作业书文本，s2=风险管控多模态


@dataclass
class SubAgentConfig:
    """SubAgent 运行配置（从 Explorer 传入）。

    Explorer A 和 B 的配置完全相同，唯一区别是 temperature：
      Explorer A: temperature=0.2（采样多样性 → 可能发现不同问题）
      Explorer B: temperature=0.0（确定性输出）
    Critic 看两份结果的差异来判断哪些 finding 更可靠。
    """
    role: Role = "b"
    scenario: Scenario = "s1"
    explorer_model: str = ""          # A/B 共用同一个模型
    critic_model: str = ""            # Critic 层专用
    vision_model: str = ""            # 场景二视觉模型
    temperature: float = 0.0          # A=0.2, B=0.0, audit=0.0


# ── SubAgent 基类 ─────────────────────────────────────────────────────────────

class SubAgent:
    """单维度审核子智能体基类。"""

    dimension: str = ""
    requires_vision: bool = False     # 场景二视觉 SubAgent 标记

    def run(
        self,
        chunks: list[dict[str, Any]],
        cfg: SubAgentConfig,
        image_chunks: list[dict[str, Any]] | None = None,
    ) -> AgentResult:
        raise NotImplementedError

    def _uncertain(self, reason: str) -> AgentResult:
        return AgentResult(
            dimension=self.dimension,
            verdict="uncertain",
            confidence=10,
            details=reason,
            need_human_review=True,
        )


# ── 文本 SubAgent（复用现有 agent，加 role 偏置）────────────────────────────

class TextSubAgent(SubAgent):
    """用现有 BaseAgent 实现的文本 SubAgent。

    Explorer A 和 B 使用完全相同的 prompt 和模型，
    唯一区别是 temperature（通过 cfg.temperature 控制）。
    Critic 通过对比两份输出的差异来判断 finding 可靠性。
    """

    def __init__(self, agent_instance: Any) -> None:
        self._agent = agent_instance
        self.dimension = agent_instance.dimension

    def run(
        self,
        chunks: list[dict[str, Any]],
        cfg: SubAgentConfig,
        image_chunks: list[dict[str, Any]] | None = None,
    ) -> AgentResult:
        # 统一用 explorer_model，A/B 完全相同
        original_model = getattr(self._agent, "text_model", "")
        if cfg.explorer_model:
            self._agent.text_model = cfg.explorer_model

        # 唯一区别：temperature（A=0.2 多样性, B=0.0 确定性）
        original_temp = getattr(self._agent, "temperature", 0.0)
        self._agent.temperature = cfg.temperature

        try:
            result = self._agent.run(chunks)
        finally:
            self._agent.text_model = original_model
            self._agent.temperature = original_temp

        return result


# ── 视觉 SubAgent（场景二专属）────────────────────────────────────────────────

class VisionSubAgent(SubAgent):
    """场景二：调用视觉模型分析图片，输出结构化 AgentResult。"""

    requires_vision = True

    def __init__(
        self,
        dimension: str,
        provider: Any,
        checklist: list[str],
    ) -> None:
        self.dimension = dimension
        self._provider = provider
        self._checklist = checklist

    def run(
        self,
        chunks: list[dict[str, Any]],
        cfg: SubAgentConfig,
        image_chunks: list[dict[str, Any]] | None = None,
    ) -> AgentResult:
        if not image_chunks:
            return self._uncertain("无图片块，跳过视觉审核")

        from src.agents.base import Finding, parse_json_response

        all_findings: list[Finding] = []
        total_confidence = 0
        analyzed = 0

        for img in image_chunks:
            img_path = img.get("image_path", "")
            if not img_path:
                continue
            cl_str = "\n".join(f"- {item}" for item in self._checklist)
            prompt = (
                f"分析这张【{self.dimension}】类型的图片，"
                "按以下检查项输出 JSON（每项值为 true/false/uncertain/描述），"
                f"另加 confidence(0.0-1.0)：\n{cl_str}\n只输出 JSON。"
            )
            try:
                raw = self._provider.call_vision(
                    image_path=img_path,
                    prompt=prompt,
                    model=cfg.vision_model,
                )
                data = parse_json_response(raw)
                conf = int(float(data.get("confidence", 0.7)) * 100)
                total_confidence += conf
                analyzed += 1

                for key, val in data.items():
                    if key == "confidence":
                        continue
                    if val is False or (isinstance(val, str) and "uncertain" in val.lower()):
                        all_findings.append(Finding(
                            severity="medium",
                            description=f"{key}: {val}",
                            evidence=f"图片: {img.get('chunk_id', '')}",
                            chunk_id=img.get("chunk_id"),
                        ))
            except Exception as e:
                log.warning("[%s] 视觉分析失败 %s: %s", self.dimension, img_path, e)

        if not analyzed:
            return self._uncertain("所有图片分析均失败")

        avg_conf = total_confidence // analyzed
        verdict = "pass" if not all_findings else ("partial" if avg_conf >= 60 else "fail")
        return AgentResult(
            dimension=self.dimension,
            verdict=verdict,
            score=max(0, 12 - len(all_findings) * 2),
            confidence=avg_conf,
            findings=all_findings,
            details=f"分析了 {analyzed} 张图片，发现 {len(all_findings)} 个问题",
            need_human_review=avg_conf < 60,
        )


# ── SubAgent 工厂 ─────────────────────────────────────────────────────────────

def build_sub_agents(
    provider: Any,
    repo: Any,
    scenario: Scenario,
    *,
    explorer_model: str,
    critic_model: str,
    vision_model: str = "",
) -> dict[str, SubAgent]:
    """
    构建该场景所需的全部 SubAgent。场景一/二完全独立，无共用 Agent。

    场景一（s1）：C1-C5 + E1-E2 + L2（作业指导书文本维度）
    场景二（s2）：I1-I8 + L1-L6（高后果区多模态维度）
    """
    if scenario == "s2":
        return _build_s2_agents(provider, repo, explorer_model, vision_model)
    return _build_s1_agents(provider, repo, explorer_model)


def _build_s1_agents(
    provider: Any,
    repo: Any,
    explorer_model: str,
) -> dict[str, SubAgent]:
    """场景一：C1-C5 + E1-E2 + L2，全部来自 src.agents.scene1。"""
    from src.agents.scene1.c1_structure import C1StructureAgent
    from src.agents.scene1.c2_content import C2ContentAgent
    from src.agents.scene1.c3_language import C3LanguageAgent
    from src.agents.scene1.c4_reference import C4ReferenceAgent
    from src.agents.scene1.c5_logic import C5LogicAgent
    from src.agents.scene1.e1_staffing import E1StaffingAgent
    from src.agents.scene1.e2_emergency import E2EmergencyAgent
    from src.agents.scene1.l2_standards import L2StandardsAgent

    return {
        "C1_structure":           TextSubAgent(C1StructureAgent(provider, explorer_model)),
        "C2_content_completeness":TextSubAgent(C2ContentAgent(provider, explorer_model, repo=repo)),
        "C3_language":            TextSubAgent(C3LanguageAgent(provider, explorer_model, repo=repo)),
        "C4_reference":           TextSubAgent(C4ReferenceAgent(provider, explorer_model)),
        "C5_logic":               TextSubAgent(C5LogicAgent(provider, explorer_model, repo=repo)),
        "E1_staffing":            TextSubAgent(E1StaffingAgent(provider, explorer_model)),
        "E2_emergency":           TextSubAgent(E2EmergencyAgent(provider, explorer_model, repo=repo)),
        "L2_standards":           TextSubAgent(L2StandardsAgent(provider, explorer_model, repo=repo)),
    }


def _build_s2_agents(
    provider: Any,
    repo: Any,
    explorer_model: str,
    vision_model: str,
) -> dict[str, SubAgent]:
    flow_mode = os.getenv("INDUSTRY_S2_FLOW_MODE", "").strip().lower()
    if flow_mode in {"legacy", "legacy_qzq", "qzq"}:
        log.info("[_build_s2_agents] use legacy qzq flow, mode=%s", flow_mode)
        return _build_s2_agents_legacy(provider, repo, explorer_model, vision_model)

    """场景二：I1-I8 + L1-L6，全部来自 src.agents.scene2。"""
    log.info("[_build_s2_agents] vision_model=%s explorer_model=%s", vision_model, explorer_model)
    from src.agents.scene2.i1_signature import I1SignatureAgent
    from src.agents.scene2.i2_required_images import I2RequiredImagesAgent
    from src.agents.scene2.i3_aerial import I3AerialAgent
    from src.agents.scene2.i4_entry_route import I4EntryRouteAgent
    from src.agents.scene2.i5_evacuation import I5EvacuationAgent
    from src.agents.scene2.i6_water_containment import I6WaterContainmentAgent
    from src.agents.scene2.i7_municipal_crossing import I7MunicipalCrossingAgent
    from src.agents.scene2.i8_image_text_consistency import I8ImageTextConsistencyAgent
    from src.agents.scene2.l1_context_consistency import L1ContextConsistencyAgent
    from src.agents.scene2.l2_standards import L2StandardsAgent
    from src.agents.scene2.l3_required_sections import L3RequiredSectionsAgent
    from src.agents.scene2.l4_time_sequence import L4TimeSequenceAgent
    from src.agents.scene2.l5_data_logic import L5DataLogicAgent
    from src.agents.scene2.l6_text_template import L6TextTemplateAgent

    # VisionAgent 包装：run(image_chunks) → SubAgent 接口
    class _VisionSubAgent(SubAgent):
        requires_vision = True

        def __init__(self, agent_instance: Any) -> None:
            self._agent = agent_instance
            self.dimension = agent_instance.dimension

        def run(self, chunks: list[dict[str, Any]], cfg: SubAgentConfig,
                image_chunks: list[dict[str, Any]] | None = None) -> AgentResult:
            return self._agent.run(image_chunks or [])

    # 混合 Agent 包装：run(chunks, image_chunks) → SubAgent 接口
    class _MixedSubAgent(SubAgent):
        requires_vision = True

        def __init__(self, agent_instance: Any) -> None:
            self._agent = agent_instance
            self.dimension = agent_instance.dimension

        def run(self, chunks: list[dict[str, Any]], cfg: SubAgentConfig,
                image_chunks: list[dict[str, Any]] | None = None) -> AgentResult:
            return self._agent.run(chunks, image_chunks or [])

    agents: dict[str, SubAgent] = {}

    # I1/I3/I4/I5/I6/I7：VisionAgent
    if vision_model:
        for AgentCls in [I1SignatureAgent, I3AerialAgent, I4EntryRouteAgent,
                         I5EvacuationAgent, I6WaterContainmentAgent,
                         I7MunicipalCrossingAgent]:
            inst = AgentCls(provider, vision_model)
            agents[inst.dimension] = _VisionSubAgent(inst)

    # I2/I8：双输入（文本 + 图片）
    agents["I2_required_images"]       = _MixedSubAgent(I2RequiredImagesAgent(provider, explorer_model))
    agents["I8_image_text_consistency"]= _MixedSubAgent(I8ImageTextConsistencyAgent(provider, explorer_model, repo=repo))

    # L1-L6：纯文本
    agents["L1_context_consistency"]   = TextSubAgent(L1ContextConsistencyAgent(provider, explorer_model))
    agents["L2_standards"]             = TextSubAgent(L2StandardsAgent(provider, explorer_model))
    agents["L3_required_sections"]     = TextSubAgent(L3RequiredSectionsAgent(provider, explorer_model))
    agents["L4_time_sequence"]         = TextSubAgent(L4TimeSequenceAgent(provider, explorer_model))
    agents["L5_data_logic"]            = TextSubAgent(L5DataLogicAgent(provider, explorer_model))
    agents["L6_text_template"]         = TextSubAgent(L6TextTemplateAgent(provider, explorer_model, repo=repo))

    log.info("[_build_s2_agents] agents created: %s", sorted(agents.keys()))
    return agents


def _build_s2_agents_legacy(
    provider: Any,
    repo: Any,
    explorer_model: str,
    vision_model: str,
) -> dict[str, SubAgent]:
    """场景二旧版流程：对齐 qzq_addwork2 的 I1-I6 + L1/L2/L3/L4/L5/L6。"""
    from src.agents.scene2.l2_standards import L2StandardsAgent
    from src.agents.scene2.legacy_image_agents import (
        I1EvacuationRouteAgent,
        I2AssemblyPointAgent,
        I3MaterialAgent,
        I4EntryRouteAgent,
        I5HCAAerialAgent,
        I6ApprovalPageAgent,
    )
    from src.agents.scene2.legacy_text_agents import (
        L1FormatAgent,
        L3SemanticAgent,
        L4RiskAgent,
        L5EmergencyAgent,
        L6ProfessionalAgent,
    )

    # legacy 维度 -> 当前 image_chunks 中的语义 image_type
    legacy_dim_to_image_types: dict[str, set[str]] = {
        "I1_evacuation_route": {"evacuation_route", "I1_evacuation_route"},
        "I2_assembly_point": {"assembly_point", "I2_assembly_point"},
        "I3_material": {"emergency_assets", "I3_material"},
        "I4_entry_route": {"entry_route", "I4_entry_route"},
        "I5_hca_aerial": {"hca_aerial", "I5_hca_aerial"},
        "I6_approval_page": {"approval", "I6_approval_page"},
    }

    class _LegacyImageSubAgent(SubAgent):
        requires_vision = True

        def __init__(self, agent_instance: Any) -> None:
            self._agent = agent_instance
            self.dimension = agent_instance.dimension

        def run(
            self,
            chunks: list[dict[str, Any]],
            cfg: SubAgentConfig,
            image_chunks: list[dict[str, Any]] | None = None,
        ) -> AgentResult:
            allowed_types = legacy_dim_to_image_types.get(self.dimension, set())
            filtered = [
                ic for ic in (image_chunks or [])
                if ic.get("image_path") and ic.get("image_type") in allowed_types
            ]
            img_paths = [str(ic.get("image_path", "")) for ic in filtered]
            if cfg.vision_model:
                self._agent._vision_model = cfg.vision_model
            return self._agent.run(img_paths)

    agents: dict[str, SubAgent] = {}
    if vision_model:
        for agent_cls in [
            I1EvacuationRouteAgent,
            I2AssemblyPointAgent,
            I3MaterialAgent,
            I4EntryRouteAgent,
            I5HCAAerialAgent,
            I6ApprovalPageAgent,
        ]:
            inst = agent_cls(provider, vision_model)
            agents[inst.dimension] = _LegacyImageSubAgent(inst)

    agents["L1_format"] = TextSubAgent(L1FormatAgent(provider, explorer_model))
    agents["L2_standards"] = TextSubAgent(L2StandardsAgent(provider, explorer_model))
    agents["L3_semantic"] = TextSubAgent(L3SemanticAgent(provider, explorer_model))
    agents["L4_risk_identification"] = TextSubAgent(L4RiskAgent(provider, explorer_model))
    agents["L5_emergency_measures"] = TextSubAgent(L5EmergencyAgent(provider, explorer_model, repo=repo))
    agents["L6_professional"] = TextSubAgent(L6ProfessionalAgent(provider, explorer_model, repo=repo))

    log.info("[_build_s2_agents_legacy] agents created: %s", sorted(agents.keys()))
    return agents
