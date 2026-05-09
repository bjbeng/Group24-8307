"""L3 必备章节完整性 —— 对照 GB46767/DB11_T2326 模板。

检查文档标题中是否包含场景二一区一案模板的核心章节。
"""

from __future__ import annotations

from typing import Any

from src.agents.base import AgentResult, BaseAgent, Finding


_DIM = "L3_required_sections"


# 必备章节及其同义词列表
S2_REQUIRED_SECTIONS: dict[str, list[str]] = {
    "高后果区基本信息": ["基本信息", "高后果区信息", "高后果区情况", "高后果区基本情况"],
    "风险评价": ["风险评价", "风险评估", "风险分析", "风险识别"],
    "管控措施": ["管控措施", "风险管控", "防控措施", "管理措施", "控制措施"],
    "应急处置": ["应急处置", "应急响应", "应急预案", "应急管理"],
    "签字审批": ["签字", "审批", "评审", "审核签字", "签发"],
    "防护目标": ["防护目标", "重点防护", "保护目标", "周边防护目标"],
    "现场处置": ["现场处置", "应急处置卡", "现场救援", "现场抢险"],
}


class L3RequiredSectionsAgent(BaseAgent):
    dimension = _DIM

    def __init__(self, provider=None, text_model="", *, repo=None,
                 temperature: float = 0.0):
        super().__init__(provider, text_model, temperature=temperature)
        self.repo = repo

    def run(self, chunks: list[dict[str, Any]]) -> AgentResult:
        # 收集所有标题（heading 类型 + chunks 的 title 字段）
        titles: list[str] = []
        for c in chunks:
            if c.get("chunk_type") == "heading" and c.get("content"):
                titles.append(c["content"])
            t = c.get("title") or ""
            if t and t not in titles:
                titles.append(t)
        title_blob = "\n".join(titles)

        if not titles:
            return AgentResult(
                dimension=self.dimension,
                verdict="uncertain", score=0, confidence=20,
                details="文档未识别出任何标题，无法判断章节完整性。",
                need_human_review=True,
            )

        findings: list[Finding] = []
        hits: dict[str, bool] = {}
        for canonical, synonyms in S2_REQUIRED_SECTIONS.items():
            hit = any(s in title_blob for s in synonyms)
            hits[canonical] = hit
            if not hit:
                findings.append(Finding(
                    severity="medium",
                    description=f"缺少必备章节：{canonical}（同义词均未命中）",
                    evidence=f"同义词={synonyms}",
                    rule_id="L3.missing_section",
                ))

        coverage = sum(1 for v in hits.values() if v) / max(1, len(hits))
        if coverage >= 0.85:
            verdict, score, conf = "pass", 12, 90
        elif coverage >= 0.6:
            verdict, score, conf = "partial", 8, 80
        else:
            verdict, score, conf = "fail", 4, 80

        return AgentResult(
            dimension=self.dimension,
            verdict=verdict, score=score, confidence=conf,
            findings=findings,
            details=f"必备章节覆盖率 {coverage:.0%}（{sum(hits.values())}/{len(hits)}）",
            extra={"section_hits": hits, "coverage": round(coverage, 3)},
        )
