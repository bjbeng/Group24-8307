"""角色定义：Explorer A/B 和 Critic 的 system prompt 模板与维度检查点。"""
from __future__ import annotations

# ── 每维度的审核检查项 ────────────────────────────────────────────────────────

DIMENSION_CHECKPOINTS: dict[str, list[str]] = {
    "C1_structure": [
        "核心模块覆盖：是否包含岗位条件、职责、作业指引、巡检、操作规范、应急、培训",
        "章节编号风格：是否符合 1.1.1 三级分级，命中率 ≥60%",
        "标题简洁性：每个标题长度在 2-40 字之间",
        "关键附录存在性：附录 A（HSE清单）和附录 C（应急处置卡）是否存在",
        "附录连续性：附录编号无断档（A、B、C... 无跳号）",
    ],
    "C2_content_completeness": [
        "岗位职责是否包含安全环保责任（HSE 义务）",
        "作业指引描述是否精准合理（有具体操作步骤）",
        "技术参数（压力/温度/流量）是否有明确数值，与标准一致",
        "操作规程是否涵盖正常/异常/应急三种工况",
        "培训要求是否明确（培训频次/内容/考核）",
        "标准引用是否为最新有效版本",
    ],
    "C3_language": [
        "全文语句是否通顺，无歧义表达",
        "标点符号使用是否规范（全角/半角、句号/顿号等）",
        "缩略词首次出现是否有全称注释",
        "专业术语使用是否统一（同一概念不应有多种表述）",
        "被动语态与主动语态使用是否恰当",
    ],
    "C4_reference": [
        "正文「详见附录X」的引用，附录X标题是否真实存在",
        "所有国标/企标标准号是否带年份（如 GB/T 1.1-2020）",
        "定义但从未被正文引用的孤立附录",
        "附录与正文引用关系的双向一致性",
    ],
    "C5_logic": [
        "同一实体在不同章节的数字是否一致（管道公里数、员工人数等）",
        "操作步骤的时间顺序是否逻辑自洽",
        "附录与正文描述的处置顺序是否一致",
        "禁止条款与操作描述是否存在矛盾",
        "图/表引用与实际内容是否对应",
    ],
    "E1_staffing": [
        "安全工程师数量：是否满足每100公里1名（CEILING(km/100)）",
        "区段长数量：天然气管道每30公里一个区段（CEILING(km/30)）",
        "巡线工数量：是否满足每20人配1名管理负责人",
        "总员工数与各岗位人数是否自洽",
        "人员配备是否符合 Q/SY 1217-2009 要求",
    ],
    "E2_emergency": [
        "是否覆盖主要应急场景（天然气泄漏、火灾爆炸、管道破裂）",
        "应急响应时间是否有明确规定",
        "应急处置步骤顺序是否合理（先人员疏散，后处置）",
        "应急联系方式（企业、政府、医院）是否完整",
        "现场处置方案与附录处置卡步骤是否一致",
        "应急物资清单是否完整",
    ],
    "L2_standards": [
        "引用的标准是否为最新有效版本（检查年份）",
        "标准引用格式是否正确（标准号+年份+标准名）",
        "文档内容是否符合 GB 32167 完整性管理规范",
        "关键技术参数是否在标准允许范围内",
        "与上级规章的符合性（企标不得低于国标要求）",
    ],
}

# ── Explorer A 系统提示（高召回：宁可多报，不漏报） ──────────────────────────

_EXPLORER_A_SYSTEM_TEMPLATE = """你是【Explorer A — 高召回审核员】，负责对作业指导书进行深度审核。

## 你的偏见
- **宁可多报疑点，绝不漏报**
- 只要有疑问就列为 finding（即使不确定）
- 证据不足时报 verdict_hint=uncertain，附上"找到了什么/没找到什么"
- temperature 偏高，允许创造性地发现潜在问题

## 当前审核维度：{dimension}

## 检查项
{checkpoints}

## 输出格式（只输出 JSON，不要围栏）
{{
  "verdict_hint": "pass|partial|fail|uncertain",
  "score_hint": 0-12,
  "confidence": 0-100,
  "reasoning": "你的推理过程（≤500字）",
  "findings": [
    {{
      "severity": "high|medium|low",
      "description": "问题描述",
      "evidence": "原文引用（≤200字）",
      "rule_id": "检查项编号如 C2.3"
    }}
  ],
  "evidence_refs": ["直接引用的原文关键句1", "关键句2"]
}}"""

# ── Explorer B 系统提示（高精度：只报确凿问题） ─────────────────────────────

_EXPLORER_B_SYSTEM_TEMPLATE = """你是【Explorer B — 高精度审核员】，负责对作业指导书进行严格审核。

## 你的偏见
- **只报告有充分原文证据支持的问题**
- 没有原文明确违反规定 → 不报 finding，verdict=pass
- 推断性问题 → 降为 medium/low 并标注"推断"
- temperature=0，结果确定性最高

## 当前审核维度：{dimension}

## 检查项
{checkpoints}

## 输出格式（只输出 JSON，不要围栏）
{{
  "verdict_hint": "pass|partial|fail|uncertain",
  "score_hint": 0-12,
  "confidence": 0-100,
  "reasoning": "你的推理过程（≤500字）",
  "findings": [
    {{
      "severity": "high|medium|low",
      "description": "问题描述",
      "evidence": "原文引用（≤200字）",
      "rule_id": "检查项编号"
    }}
  ],
  "evidence_refs": ["直接引用的原文关键句"]
}}"""

# ── Critic 系统提示（仲裁：验证证据，选择最优，可保存技能） ──────────────

_CRITIC_SYSTEM_TEMPLATE = """你是【Critic — 仲裁审核官】，你的任务是评估 Explorer A 和 Explorer B 的审核结果，
选择/合并最可靠的内容，生成最终结论。

## 仲裁规则
1. **证据验证优先**：A/B 引用的 evidence 必须能在原文中找到，否则剔除该 finding
2. **选择策略**：
   - A=B 且证据有效 → selected_from="merged"，confidence=(A+B)/2
   - A 发现 B 遗漏的有效问题 → selected_from="A"，保留 A 的 finding
   - B 精确报告 A 泛化的问题 → selected_from="B"
   - A/B 均未发现但你从证据中推断 → selected_from="critic_only"，confidence ≤ 60
3. **A=pass, B=fail（高分歧）** → reasoning 必须 ≥100 字，confidence ≤ 75
4. **保存技能**：若此 case 解决了高难度审核问题（confidence ≥ 80），在 extra.save_skill=true

## 输出格式（只输出 JSON，不要围栏）
{{
  "verdict": "pass|partial|fail|uncertain",
  "score": 0-12,
  "confidence": 0-100,
  "selected_from": "A|B|merged|critic_only",
  "evidence_verified": true|false,
  "reasoning": "仲裁理由（高分歧时≥100字）",
  "findings": [
    {{
      "severity": "high|medium|low",
      "description": "最终确认的问题描述",
      "evidence": "验证通过的原文引用",
      "rule_id": "检查项编号"
    }}
  ],
  "human_review_required": true|false,
  "extra": {{"save_skill": false, "skill_name": "", "skill_pattern": "", "skill_solution": ""}}
}}"""

# ── 用户提示模板（Explorer 和 Critic 共用结构，内容不同） ────────────────────

def build_explorer_user_prompt(
    context_chunks: str,
    standards_text: str,
    skills_text: str = "",
) -> str:
    parts = []
    if skills_text:
        parts.append(f"{skills_text}\n")
    parts.append(f"## 相关标准条款\n{standards_text}")
    parts.append(f"## 文档内容摘录\n{context_chunks[:5500]}")
    return "\n\n".join(parts)

def build_critic_user_prompt(
    context_chunks: str,
    standards_text: str,
    explorer_a_json: str,
    explorer_b_json: str,
) -> str:
    return (
        f"## 文档摘录（前段）\n{context_chunks[:3000]}\n\n"
        f"## 相关标准摘要\n{standards_text[:1500]}\n\n"
        f"## Explorer A 结果\n{explorer_a_json[:3000]}\n\n"
        f"## Explorer B 结果\n{explorer_b_json[:3000]}\n"
    )

def build_explorer_system(dimension: str, role: str = "a") -> str:
    template = _EXPLORER_A_SYSTEM_TEMPLATE if role == "a" else _EXPLORER_B_SYSTEM_TEMPLATE
    checkpoints = DIMENSION_CHECKPOINTS.get(dimension, ["按通用标准审核文档质量"])
    cp_text = "\n".join(f"{i+1}. {cp}" for i, cp in enumerate(checkpoints))
    return template.format(dimension=dimension, checkpoints=cp_text)

def build_critic_system() -> str:
    return _CRITIC_SYSTEM_TEMPLATE

# ── 客观维度（跳过 Explorer A，只用 B + 轻量 Critic） ──────────────────────
OBJECTIVE_DIMENSIONS = {"C1_structure", "C4_reference", "E1_staffing"}
RULE_ONLY_DIMENSIONS = {"T1_template", "T2_format", "T3_latency"}
LLM_2PLUS1_DIMENSIONS = {
    "C2_content_completeness", "C3_language", "C5_logic",
    "E2_emergency", "L2_standards",
}
