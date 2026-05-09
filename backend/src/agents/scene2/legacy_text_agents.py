"""场景二旧版 L1/L3/L4/L5/L6 文本 Agent（对齐 qzq_addwork2 流程）。"""
from __future__ import annotations

import logging
from typing import Any

from src.agents.base import AgentResult, BaseAgent, parse_json_response
from src.agents.llm_audit_utils import (
    agent_result_from_llm_json,
    build_json_only_system,
    collect_excerpt,
    format_snippets_for_prompt,
    retrieve_standard_snippets,
)
from src.llm import Message
from src.llm.provider import LLMProvider
from src.store.repository import Repository

log = logging.getLogger(__name__)


class L1FormatAgent(BaseAgent):
    dimension = "L1_format"
    _KEYWORDS = (
        "封面", "目录", "审批", "签字", "日期", "编制", "审核", "批准",
        "高后果区", "管控方案", "章节", "附件",
    )

    def run(self, chunks: list[dict[str, Any]]) -> AgentResult:
        excerpt = collect_excerpt(chunks, self._KEYWORDS, max_chars=4000)
        if not excerpt.strip():
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                confidence=15,
                details="文档内容不足",
                need_human_review=True,
            )
        system = build_json_only_system(
            "你是油气管道行业文件格式审核专家。审核《高后果区风险管控方案》的格式规范：\n"
            "1. 封面是否包含：方案名称、管道名称、管段编号、编制单位、日期\n"
            "2. 目录是否齐全，页码是否对应\n"
            "3. 章节编号是否规范（1. 1.1 1.1.1 格式）\n"
            "4. 审批签字栏是否有编制/审核/批准三栏\n"
            "5. 页眉页脚是否规范\n"
            "score说明：12=格式完全规范，8-11=小问题，4-7=较多缺项，0-3=严重不符。"
        )
        user = f"## 文档摘录\n{excerpt[:3500]}\n"
        try:
            raw = self.provider.call_text(
                [Message(role="system", content=system), Message(role="user", content=user)],
                model=self.text_model,
                temperature=self.temperature,
                max_tokens=800,
            )
            data = parse_json_response(raw) or {}
        except Exception as e:
            log.warning("L1 LLM 失败: %s", e)
            data = {}
        if not data:
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                confidence=20,
                details="LLM 未返回有效结果",
                need_human_review=True,
            )
        return agent_result_from_llm_json(data, dimension=self.dimension, max_score=12)


class L3SemanticAgent(BaseAgent):
    dimension = "L3_semantic"
    _KEYWORDS = (
        "管段", "范围", "桩号", "公里", "km", "高后果区", "人员", "负责人",
        "措施", "处置", "应急", "联系", "巡检", "频次",
    )

    def run(self, chunks: list[dict[str, Any]]) -> AgentResult:
        excerpt = collect_excerpt(chunks, self._KEYWORDS, max_chars=5000)
        if not excerpt.strip():
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                confidence=15,
                details="内容不足",
                need_human_review=True,
            )
        system = build_json_only_system(
            "你是油气管道安全审核专家。检查《高后果区风险管控方案》的语义逻辑一致性：\n"
            "1. 管段范围（桩号/公里）在不同章节是否一致\n"
            "2. 人员配备数量前后是否矛盾\n"
            "3. 风险等级描述与防控措施是否匹配\n"
            "4. 时间节点/频次表述是否前后一致\n"
            "5. 附件/图片引用与正文是否对应\n"
            "score: 12=完全一致，8-11=微小矛盾，4-7=明显矛盾，0-3=严重逻辑错误。"
        )
        user = f"## 文档摘录\n{excerpt[:4500]}\n"
        try:
            raw = self.provider.call_text(
                [Message(role="system", content=system), Message(role="user", content=user)],
                model=self.text_model,
                temperature=self.temperature,
                max_tokens=1000,
            )
            data = parse_json_response(raw) or {}
        except Exception as e:
            log.warning("L3 LLM 失败: %s", e)
            data = {}
        if not data:
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                confidence=20,
                details="LLM 未返回有效结果",
                need_human_review=True,
            )
        return agent_result_from_llm_json(data, dimension=self.dimension, max_score=12)


class L4RiskAgent(BaseAgent):
    dimension = "L4_risk_identification"
    _KEYWORDS = (
        "风险", "隐患", "危险", "高后果", "影响范围", "敏感目标",
        "居民", "学校", "医院", "人口", "建筑", "穿越",
    )

    def run(self, chunks: list[dict[str, Any]]) -> AgentResult:
        excerpt = collect_excerpt(chunks, self._KEYWORDS, max_chars=5000)
        if not excerpt.strip():
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                confidence=15,
                details="风险描述内容不足",
                need_human_review=True,
            )
        system = build_json_only_system(
            "你是管道完整性专家。审核高后果区风险点识别的完整性：\n"
            "1. 是否识别了周边敏感目标（居民区/学校/医院/人员密集场所）\n"
            "2. 影响范围计算是否合理（天然气管道高后果区判定标准）\n"
            "3. 风险等级划分是否符合 GB 32167\n"
            "4. 是否覆盖了腐蚀/第三方破坏/自然灾害等主要风险类型\n"
            "5. 历史事故/隐患记录是否纳入分析\n"
            "score: 12=识别完整，8-11=有遗漏，4-7=明显缺项，0-3=严重不足。"
        )
        user = f"## 文档摘录\n{excerpt[:4500]}\n"
        try:
            raw = self.provider.call_text(
                [Message(role="system", content=system), Message(role="user", content=user)],
                model=self.text_model,
                temperature=self.temperature,
                max_tokens=1000,
            )
            data = parse_json_response(raw) or {}
        except Exception as e:
            log.warning("L4 LLM 失败: %s", e)
            data = {}
        if not data:
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                confidence=20,
                details="LLM 未返回有效结果",
                need_human_review=True,
            )
        return agent_result_from_llm_json(data, dimension=self.dimension, max_score=12)


class L5EmergencyAgent(BaseAgent):
    dimension = "L5_emergency_measures"
    _KEYWORDS = (
        "应急", "预案", "处置", "疏散", "报警", "联系", "抢险",
        "警戒", "隔离", "通知", "响应", "启动", "终止",
    )

    def __init__(self, provider: LLMProvider, text_model: str, repo: Repository | None = None, temperature: float = 0.0) -> None:
        super().__init__(provider, text_model, temperature=temperature)
        self.repo = repo

    def run(self, chunks: list[dict[str, Any]]) -> AgentResult:
        excerpt = collect_excerpt(chunks, self._KEYWORDS, max_chars=5000)
        if not excerpt.strip():
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                confidence=15,
                details="应急内容不足",
                need_human_review=True,
            )

        snippets = retrieve_standard_snippets(self.repo, "E2_emergency", excerpt[:500], top_k=3)
        std_text = format_snippets_for_prompt(snippets) if snippets else "（无标准检索结果）"

        system = build_json_only_system(
            "你是应急管理专家。审核高后果区风险管控方案的应急措施完整性：\n"
            "1. 是否有明确的应急响应级别和启动条件\n"
            "2. 疏散路线和集合点是否有具体描述（与图纸对应）\n"
            "3. 报警联络程序（内部/政府/公众）是否完整\n"
            "4. 应急物资和设备清单是否具体\n"
            "5. 现场处置步骤是否逻辑严谨（符合 QSY 1217/AQ 3057）\n"
            "6. 应急结束/善后处置程序是否有\n"
            "score: 12=完整规范，8-11=有缺项，4-7=明显不足，0-3=严重缺失。"
        )
        user = f"## 相关标准\n{std_text[:1000]}\n\n## 文档摘录\n{excerpt[:4000]}\n"
        try:
            raw = self.provider.call_text(
                [Message(role="system", content=system), Message(role="user", content=user)],
                model=self.text_model,
                temperature=self.temperature,
                max_tokens=1000,
            )
            data = parse_json_response(raw) or {}
        except Exception as e:
            log.warning("L5 LLM 失败: %s", e)
            data = {}
        if not data:
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                confidence=20,
                details="LLM 未返回有效结果",
                need_human_review=True,
            )
        return agent_result_from_llm_json(data, dimension=self.dimension, max_score=12)


class L6ProfessionalAgent(BaseAgent):
    dimension = "L6_professional"
    _KEYWORDS = (
        "MPa", "压力", "管径", "壁厚", "材质", "钢级", "腐蚀",
        "阴极保护", "绝缘", "检测", "评价", "完整性", "SCADA",
    )

    def __init__(self, provider: LLMProvider, text_model: str, repo: Repository | None = None, temperature: float = 0.0) -> None:
        super().__init__(provider, text_model, temperature=temperature)
        self.repo = repo

    def run(self, chunks: list[dict[str, Any]]) -> AgentResult:
        excerpt = collect_excerpt(chunks, self._KEYWORDS, max_chars=4000)
        if not excerpt.strip():
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                confidence=15,
                details="专业技术内容不足",
                need_human_review=True,
            )

        snippets = retrieve_standard_snippets(self.repo, "L2_standards", excerpt[:400], top_k=3)
        std_text = format_snippets_for_prompt(snippets) if snippets else "（无标准检索结果）"

        system = build_json_only_system(
            "你是管道完整性工程专家。审核方案的专业技术准确性：\n"
            "1. 管道技术参数（压力/管径/材质）是否准确描述\n"
            "2. 专业术语使用是否规范\n"
            "3. 引用的技术标准是否现行有效（GB 32167/SY/T 6648等）\n"
            "4. 风险评价方法是否符合行业规范\n"
            "5. 阴极保护/腐蚀检测等专业措施描述是否准确\n"
            "score: 12=专业性强，8-11=基本准确有小问题，4-7=较多错误，0-3=严重不专业。"
        )
        user = f"## 相关标准\n{std_text[:800]}\n\n## 文档摘录\n{excerpt[:3500]}\n"
        try:
            raw = self.provider.call_text(
                [Message(role="system", content=system), Message(role="user", content=user)],
                model=self.text_model,
                temperature=self.temperature,
                max_tokens=800,
            )
            data = parse_json_response(raw) or {}
        except Exception as e:
            log.warning("L6 LLM 失败: %s", e)
            data = {}
        if not data:
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain",
                confidence=20,
                details="LLM 未返回有效结果",
                need_human_review=True,
            )
        return agent_result_from_llm_json(data, dimension=self.dimension, max_score=12)
