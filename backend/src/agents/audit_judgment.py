"""LLM Judgment 服务：基于 Label 详细结果生成人工可读审核意见。

Audit 系统在 agent 并行跑完之后，对每个维度的 label 结果（即 agent.extra["label"]）
调 LLM 生成人工可读的审核意见（AuditOpinion），
最终汇总为 AuditReport。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.agents.base import AgentResult, AuditOpinion, parse_json_response
from src.llm import Message, LLMProvider

log = logging.getLogger(__name__)

_AUDIT_JUDGMENT_SYSTEM = """你是文档审核专家，擅长：
1. 根据检查项的 verdict/findings，判断"缺少什么"
2. 给出具体的修改建议

你会收到一个维度的详细打标结果（包含多个检查项的 verdict、findings、evidence），
请为每个检查项生成一条人工可读意见。

要求：
- opinion 要明确说出"通过了什么"或"缺少什么/有什么问题"
- suggestions 要具体、可操作
- 如果 verdict=pass，suggestions 应为空列表
- severity 按以下规则从 verdict 推导：fail → high，partial → medium，pass → low

输出 JSON（不要 markdown 围栏）：
{
  "opinions": [
    {
      "check_item": "C1.required_modules",
      "verdict": "pass",
      "severity": "low",
      "opinion": "文档标题覆盖了全部7个核心模块，结构完整。",
      "evidence_summary": "标题包含：岗位条件、职责、作业指引、巡检、操作规范、应急、培训",
      "suggestions": []
    },
    {
      "check_item": "C1.toc_page_overflow",
      "verdict": "partial",
      "severity": "medium",
      "opinion": "目录中有 3 个条目页码超出实际文档页数（547页），分别是附录13（标注557页）、附录14（标注562页）、附录16（标注562页）。",
      "evidence_summary": "目录页标注附录13对应第557页，实际估算物理页562；附录14/16同理",
      "suggestions": [
        "重新编排附录13-16的页码，确保目录页码与实际物理页一致",
        "或检查文档是否确实有这些附录内容"
      ]
    }
  ]
}
"""


class AuditJudgmentService:
    """基于 Label 结果生成人工可读审核意见。"""

    def __init__(
        self,
        provider: LLMProvider,
        judgment_model: str,
        *,
        temperature: float = 0.1,
    ) -> None:
        self.provider = provider
        self.judgment_model = judgment_model
        self.temperature = temperature

    def run(
        self, dim_results: dict[str, AgentResult]
    ) -> dict[str, list[AuditOpinion]]:
        """对所有维度的 label 结果做 LLM judgment。

        Returns:
            dict[str, list[AuditOpinion]] - dimension → opinions
        """
        judgments: dict[str, list[AuditOpinion]] = {}

        for dim, result in dim_results.items():
            # 提取 label 数据（每个 agent.run() 都会设置 extra["label"]）
            label_data = result.extra.get("label", {})
            standards = label_data.get("standards", {})

            if not standards:
                log.debug("维度 %s 无 standards 数据，跳过 judgment", dim)
                judgments[dim] = []
                continue

            try:
                opinions = self._judgment_one_dimension(dim, standards)
                judgments[dim] = opinions
            except Exception as e:
                log.warning("维度 %s judgment 失败: %s", dim, e)
                judgments[dim] = []

        return judgments

    def _judgment_one_dimension(
        self, dimension: str, standards: dict[str, Any]
    ) -> list[AuditOpinion]:
        """为单个维度生成所有检查项的意见。"""
        payload = json.dumps(standards, ensure_ascii=False, indent=2)
        user = f"维度: {dimension}\n\n详细打标结果:\n{payload}"

        raw = self.provider.call_text(
            [
                Message(role="system", content=_AUDIT_JUDGMENT_SYSTEM),
                Message(role="user", content=user),
            ],
            model=self.judgment_model,
            temperature=self.temperature,
            max_tokens=4000,
        )

        data = parse_json_response(raw)
        opinions: list[AuditOpinion] = []

        for item in (data.get("opinions") or []):
            opinions.append(AuditOpinion(
                check_item=item.get("check_item", ""),
                verdict=item.get("verdict", "uncertain"),
                severity=item.get("severity", "medium"),
                opinion=item.get("opinion", ""),
                evidence_summary=item.get("evidence_summary", ""),
                suggestions=list(item.get("suggestions") or []),
            ))

        return opinions