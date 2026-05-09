"""C1 结构合规性 —— 纯规则维度。

赛题原文要求：
1. 目录覆盖是否全面，是否涵盖核心模块（岗位条件、职责、作业指引、巡检、
   操作规范、应急、培训等）
2. 层级逻辑是否清晰，章节编号是否符合标准（如 1.1.1 分级）
3. 标题是否简洁明确
4. 附录配套是否完整，附录是否与正文对应（HSE 清单、图纸、操作票等）
5. 关键附录是否存在（正文引用了附录但实体章节缺失，或实体存在但无内容）
6. 目录页码与实际内容是否一致（TOC 条目标题能否在正文中找到）

实现策略：纯规则。所有检查项均为确定性判断，不调用 LLM。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from src.agents.base import AgentResult, BaseAgent, Finding


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 核心模块关键词：每个内层 list 是同义词组（任一命中即视为覆盖）
# ---------------------------------------------------------------------------

REQUIRED_MODULES: list[tuple[str, list[str]]] = [
    ("岗位条件", ["岗位", "职位", "人员配置", "岗位条件", "岗位设置"]),
    ("职责",     ["职责", "责任", "管理职责", "岗位职责"]),
    ("作业指引", ["作业指引", "作业流程", "业务流程", "作业内容", "操作流程", "作业规范", "业务操作"]),
    ("巡检",     ["巡检", "巡线", "巡护", "巡视", "检查"]),
    ("操作规范", ["操作", "操作规范", "操作要求", "工艺", "规程"]),
    ("应急",     ["应急", "事故", "处置", "抢险", "应急响应"]),
    ("培训",     ["培训", "教育", "考核", "训练"]),
]

# ---------------------------------------------------------------------------
# 正则
# ---------------------------------------------------------------------------

HIERARCHICAL_RE = re.compile(r"^\s*(\d+)([.．、]\s*\d+){1,4}\s")
TOP_LEVEL_RE = re.compile(
    r"^\s*(?:第\s*[一二三四五六七八九十百千]+\s*[章节]|\d+\s*[.．、]?\s*[^.．、])"
)

# 匹配附录/附件章节标题：
#   "附录A"、"附录 B"、"附录一"（传统编号格式）
#   "9 附录"、"9 附件"（章节编号前置格式）
#   "第九章 附录"（章节中文格式）
_APP_WORD = r"附\s*[录件]"
APPENDIX_HEADING_RE = re.compile(
    r"(?:^" + _APP_WORD + r"\s*([A-Za-z一二三四五六七八九十]+)"  # 传统：附录A / 附件一
    r"|^[\d\s.．]*" + _APP_WORD + r"\s*$"                        # 章节前置：9 附录 / 9 附件
    r"|^第[一二三四五六七八九十百]+[章节]\s*" + _APP_WORD + r"\s*$)",  # 第N章 附录
    re.IGNORECASE,
)

# 匹配正文中对附录/附件的引用："见附录A"、"详见附件B"、"参照附录三"、"见附件11"
# label 捕获组支持：单字母、中文序数、多位数字
APPENDIX_REF_RE = re.compile(
    r"(?:详见|参见|见|请见|参阅|参考)\s*附\s*[录件]\s*([A-Za-z一二三四五六七八九十]|\d+)?",
    re.IGNORECASE,
)

# TOC 条目：以"目录"为章节名称的 chunk，或 chunk_type == "toc"
TOC_ENTRY_RE = re.compile(r"^(.+?)\s*\.{2,}\s*(\d+)\s*$")  # "1.1 目的..........3"

TITLE_MIN_LEN = 2
TITLE_MAX_LEN = 40


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class AppendixRef:
    """正文中一处附录引用。"""
    label: str          # "A" / "一" / "" (无具体标识)
    context: str        # 引用所在句子片段（调试用）
    chunk_id: str
    section_path: str
    paragraph_index: int


@dataclass
class AppendixSection:
    """文档中实际存在的附录章节。"""
    label: str          # "A" / "一" / ...
    title: str          # 完整标题，如 "附录A 设备参数表"
    chunk_id: str
    section_path: str
    paragraph_index: int
    has_content: bool = False   # 附录标题后是否有实质内容


@dataclass
class StructureFacts:
    headings: list[dict[str, Any]] = field(default_factory=list)
    appendix_refs: list[AppendixRef] = field(default_factory=list)
    appendix_sections: list[AppendixSection] = field(default_factory=list)
    toc_titles: list[str] = field(default_factory=list)   # 从目录页提取的标题

    @property
    def all_titles(self) -> list[str]:
        return [h["title"] for h in self.headings]

    # 向后兼容：旧代码/测试可能读 appendices_found
    @property
    def appendices_found(self) -> list[str]:
        return [s.label for s in self.appendix_sections if s.label]


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _strip_md(text: str) -> str:
    """去除 MinerU 输出的 Markdown 加粗/斜体标记（** / *），保留纯文本。"""
    return re.sub(r"\*+", "", text).strip()


def _infer_level(chunk: dict[str, Any]) -> int:
    path = chunk.get("section_path", "")
    if not path:
        return 1
    return path.count(".") + 1


def _build_toc_tree(headings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将扁平标题列表构建为带层级信息的节点列表。

    返回节点列表，每个节点含：
    - level: heading_level（1/2/3）
    - title: 标题文本
    - section_path: 章节路径
    - chunk_id: chunk id
    - paragraph_index: 页内段落索引
    """
    nodes: list[dict[str, Any]] = []
    for h in headings:
        level = h.get("heading_level") or h.get("level") or 1
        nodes.append({
            "level": level,
            "title": h.get("title", ""),
            "section_path": h.get("section_path", ""),
            "chunk_id": h.get("chunk_id", ""),
            "paragraph_index": h.get("paragraph_index", -1),
        })
    return nodes


def _format_toc_tree(nodes: list[dict[str, Any]]) -> str:
    """将目录树节点格式化为带缩进的纯文本字符串，供人工核查或 LLM 使用。"""
    lines: list[str] = []
    for n in nodes:
        indent = "  " * (n["level"] - 1)
        lines.append(f"{indent}[L{n['level']}] {n['title']}  ({n['section_path']})")
    return "\n".join(lines) if lines else "（无标题）"


# ---------------------------------------------------------------------------
# 抽取
# ---------------------------------------------------------------------------


def extract_structure(chunks: list[dict[str, Any]]) -> StructureFacts:
    """从 chunk 列表中抽取标题、附录引用、附录章节、TOC 条目。"""
    facts = StructureFacts()

    for c in chunks:
        chunk_type = (c.get("chunk_type") or "").lower()
        if chunk_type != "heading":
            continue

        title = _strip_md(c.get("title") or c.get("content") or "")
        if not title:
            continue

        level = c.get("heading_level")
        if not isinstance(level, int):
            level = _infer_level(c)

        paragraph_index = c.get("paragraph_index", -1)
        if not isinstance(paragraph_index, int):
            paragraph_index = -1

        facts.headings.append({
            "level": level,
            "title": title,
            "section_path": c.get("section_path", ""),
            "chunk_id": c.get("chunk_id", ""),
            "paragraph_index": paragraph_index,
        })

    # 先收集所有附录章节（按 index 排序后才能判断是否有后续内容）
    appendix_heading_indices: list[int] = []

    for i, c in enumerate(chunks):
        chunk_type = c.get("chunk_type", "")
        title = _strip_md(c.get("title") or "")
        content = (c.get("content") or "").strip()
        chunk_id = c.get("chunk_id", "")
        section_path = c.get("section_path", "")
        para_idx = c.get("paragraph_index", -1)

        # ---- TOC 页 ----
        if chunk_type == "toc" or title in ("目录", "CONTENTS", "Contents"):
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                m = TOC_ENTRY_RE.match(line)
                entry_title = m.group(1).strip() if m else line
                if entry_title and len(entry_title) >= TITLE_MIN_LEN:
                    facts.toc_titles.append(entry_title)

        # ---- 正文附录引用（非附录章节内部）----
        is_in_appendix = section_path.startswith("APP_")
        if not is_in_appendix:
            for m in APPENDIX_REF_RE.finditer(content):
                label = (m.group(1) or "").strip().upper()
                start = max(0, m.start() - 5)
                end = min(len(content), m.end() + 15)
                facts.appendix_refs.append(AppendixRef(
                    label=label,
                    context=content[start:end],
                    chunk_id=chunk_id,
                    section_path=section_path,
                    paragraph_index=para_idx,
                ))

        # ---- 附录章节标题 ----
        if chunk_type != "heading":
            continue
        m = APPENDIX_HEADING_RE.match(title)
        if m:
            label = (m.group(1) or "").strip().upper()
            facts.appendix_sections.append(AppendixSection(
                label=label,
                title=title,
                chunk_id=chunk_id,
                section_path=section_path,
                paragraph_index=para_idx,
            ))
            appendix_heading_indices.append(i)

    # ---- 判断附录章节是否有内容 ----
    for rank, app_sec in enumerate(facts.appendix_sections):
        src_i = appendix_heading_indices[rank]
        next_heading_i = (
            appendix_heading_indices[rank + 1]
            if rank + 1 < len(appendix_heading_indices)
            else len(chunks)
        )
        for j in range(src_i + 1, next_heading_i):
            following_content = (chunks[j].get("content") or "").strip()
            following_type = chunks[j].get("chunk_type", "")
            if following_type in ("text", "table_summary", "table_full") and len(following_content) > 20:
                app_sec.has_content = True
                break

    return facts


# ---------------------------------------------------------------------------
# 检查函数
# ---------------------------------------------------------------------------


def check_required_modules(facts: StructureFacts) -> list[Finding]:
    """C1.1 核心模块覆盖度。"""
    titles_blob = " ".join(facts.all_titles)
    findings: list[Finding] = []
    for canonical, synonyms in REQUIRED_MODULES:
        if not any(kw in titles_blob for kw in synonyms):
            findings.append(Finding(
                severity="medium",
                description=f"缺少核心模块：{canonical}（同义词均未在标题中出现）",
                rule_id="C1.required_modules",
                category="content",
                is_problem=True,
                problem_type="缺少核心模块",
                rule_basis="依据《作业指导书编制导则》第四章：作业指导书应包含岗位条件、职责、作业指引、巡检、应急、培训等核心模块",
                correction_suggestion=f"在文档合适位置增加【{canonical}】章节，内容应包含相关具体规定和操作要求",
            ))
    return findings


def check_hierarchical_numbering(facts: StructureFacts) -> list[Finding]:
    """C1.2 层级编号规范（1.1.1 分级风格，60% 达标）。"""
    if not facts.headings:
        return [Finding(
            severity="high",
            description="文档没有任何标题，结构无法识别",
            rule_id="C1.hierarchy",
            category="content",
            is_problem=True,
            problem_type="层级结构问题",
            rule_basis="依据《标准化工作导则 第1部分：标准化文件的结构和起草规则》（GB/T 1.1），标准层次一般不超过4层，编号应统一",
            correction_suggestion="重新梳理文档结构，统一使用阿拉伯数字分级编号（如1.1.1），确保层次清晰",
        )]
    sub = [h for h in facts.headings if h.get("level", 1) >= 2]
    if not sub:
        return []
    matched = sum(
        1 for h in sub
        if HIERARCHICAL_RE.match(h["title"]) or h.get("section_path")
    )
    ratio = matched / len(sub)
    if ratio < 0.6:
        return [Finding(
            severity="medium",
            description=(
                f"二级及以下标题中仅 {ratio:.0%} 符合 1.1.1 分级风格，"
                f"建议统一编号格式"
            ),
            rule_id="C1.hierarchy",
            category="content",
            is_problem=True,
            problem_type="层级结构问题",
            rule_basis="依据《标准化工作导则 第1部分：标准化文件的结构和起草规则》（GB/T 1.1），标准层次一般不超过4层，编号应统一",
            correction_suggestion="统一标题编号格式，对不符合1.1.1格式的标题进行修订",
        )]
    return []


def check_title_conciseness(facts: StructureFacts) -> list[Finding]:
    """C1.3 标题简洁明确。"""
    too_long = [h for h in facts.headings if len(h["title"]) > TITLE_MAX_LEN]
    too_short = [h for h in facts.headings if 0 < len(h["title"]) < TITLE_MIN_LEN]
    findings: list[Finding] = []
    if too_long:
        sample = too_long[0]
        findings.append(Finding(
            severity="low",
            description=f"{len(too_long)} 个标题过长（>{TITLE_MAX_LEN}字），如：{sample['title'][:30]}…",
            rule_id="C1.title_length",
            chunk_id=sample.get("chunk_id"),
            section_path=sample.get("section_path", ""),
            paragraph_index=sample.get("paragraph_index", -1),
            category="content",
            is_problem=True,
            problem_type="标题长度问题",
            rule_basis="依据《标准化工作导则 第1部分：标准化文件的结构和起草规则》（GB/T 1.1），标题应简明扼要，概括反映主题",
            correction_suggestion=f"精简标题，将过长的标题（如{sample['title'][:30]}…）控制在{TITLE_MAX_LEN}字以内",
        ))
    if too_short:
        sample = too_short[0]
        findings.append(Finding(
            severity="low",
            description=f"{len(too_short)} 个标题过短：{[h['title'] for h in too_short[:3]]}",
            rule_id="C1.title_length",
            chunk_id=sample.get("chunk_id"),
            section_path=sample.get("section_path", ""),
            paragraph_index=sample.get("paragraph_index", -1),
            category="content",
            is_problem=True,
            problem_type="标题长度问题",
            rule_basis="依据《标准化工作导则 第1部分：标准化文件的结构和起草规则》（GB/T 1.1），标题应简明扼要",
            correction_suggestion=f"扩充过于简短的标题（如{[h['title'] for h in too_short[:3]]}），使其能够准确反映章节内容",
        ))
    return findings


def check_key_appendices(facts: StructureFacts) -> list[Finding]:
    """C1.4 关键附录存在性。

    逻辑：正文引用了附录 → 对应附录章节必须存在。
    不强求附录字母顺序，不硬编码 A/C。
    """
    findings: list[Finding] = []

    if not facts.appendix_refs:
        # 正文没有引用任何附录，无强制要求
        return []

    if not facts.appendix_sections:
        # 正文有引用但文档完全没有附录章节
        ref = facts.appendix_refs[0]
        findings.append(Finding(
            severity="high",
            description=(
                f"正文共 {len(facts.appendix_refs)} 处附录引用"
                f"（如：{ref.context!r}），但文档末尾未找到任何附录章节"
            ),
            rule_id="C1.key_appendix",
            chunk_id=ref.chunk_id,
            section_path=ref.section_path,
            paragraph_index=ref.paragraph_index,
            anchor_text=ref.context[:30],
            category="content",
            is_problem=True,
            problem_type="附录缺失",
            rule_basis="依据《作业指导书编制导则》第五章：正文引用的附录必须在文档中有对应的附录章节",
            correction_suggestion="在文档末尾增加与正文引用对应的附录章节，内容应与正文引用相匹配",
        ))
        return findings

    # 检查有具体标识的引用是否有对应实体
    known_labels = {s.label.upper() for s in facts.appendix_sections if s.label}
    # 若文档有无标签的附件章节（如"9 附件"），数字型子条目引用视为已覆盖
    has_unlabeled_appendix = any(not s.label for s in facts.appendix_sections)
    seen_missing: set[str] = set()
    for ref in facts.appendix_refs:
        label = ref.label.upper()
        if not label or label in seen_missing:
            continue
        if has_unlabeled_appendix and label.isdigit():
            continue  # "附件11" 等数字引用归属于总附件章节，不单独检查
        if label not in known_labels:
            seen_missing.add(label)
            findings.append(Finding(
                severity="medium",
                description=f"正文引用了附录{label}，但文档中未找到对应附录章节",
                rule_id="C1.key_appendix",
                chunk_id=ref.chunk_id,
                section_path=ref.section_path,
                paragraph_index=ref.paragraph_index,
                anchor_text=ref.context[:30],
                category="content",
                is_problem=True,
                problem_type="附录缺失",
                rule_basis="依据《作业指导书编制导则》第五章：正文引用的附录必须在文档中有对应的附录章节",
                correction_suggestion=f"增加附录{label}章节，内容应与正文引用'详见附录{label}'相匹配",
            ))

    return findings


def check_appendix_has_content(facts: StructureFacts) -> list[Finding]:
    """C1.5 附录章节必须有实质内容（不能是空标题）。"""
    findings: list[Finding] = []
    for app in facts.appendix_sections:
        if not app.has_content:
            findings.append(Finding(
                severity="medium",
                description=f"附录{app.label}（{app.title}）章节下无实质内容",
                rule_id="C1.appendix_content",
                chunk_id=app.chunk_id,
                section_path=app.section_path,
                paragraph_index=app.paragraph_index,
                anchor_text=app.title[:30],
                category="content",
                is_problem=True,
                problem_type="附录内容缺失",
                rule_basis="依据《作业指导书编制导则》第五章：附录章节必须有实质性内容，不能仅为空标题",
                correction_suggestion=f"为附录{app.label}增加实质内容，如相关数据表格、参数清单或操作细则",
            ))
    return findings


def check_appendix_continuity(facts: StructureFacts) -> list[Finding]:
    """C1.6 附录编号连续（A→B→C 不跳号；中文序号同理）。"""
    if not facts.appendix_sections:
        return [Finding(
            severity="low",
            description="文档未识别到任何附录章节",
            rule_id="C1.appendix_continuity",
            category="content",
            is_problem=False,
            problem_type="无附录章节",
            rule_basis="依据《作业指导书编制导则》第五章：附录编号应连续规范",
            correction_suggestion="如需使用附录，应按A、B、C顺序连续编号",
        )]
    letters = sorted(
        s.label for s in facts.appendix_sections
        if len(s.label) == 1 and s.label.isalpha()
    )
    if len(letters) < 2:
        return []
    expected = [chr(ord(letters[0]) + i) for i in range(len(letters))]
    if letters != expected:
        return [Finding(
            severity="low",
            description=f"附录编号不连续：{letters}，期望 {expected}",
            rule_id="C1.appendix_continuity",
            category="content",
            is_problem=True,
            problem_type="附录编号不连续",
            rule_basis="依据《作业指导书编制导则》第五章：附录编号应按字母顺序连续编排",
            correction_suggestion=f"调整附录编号顺序，使其连续：当前{letters}，建议改为{expected}",
        )]
    return []


def check_toc_vs_body(facts: StructureFacts) -> list[Finding]:
    """C1.7 目录条目标题在正文中必须实际存在。"""
    if not facts.toc_titles:
        return []
    body_titles_set = set(facts.all_titles)
    missing = [t for t in facts.toc_titles if t not in body_titles_set]
    if not missing:
        return []
    sample = missing[:3]
    return [Finding(
        severity="medium",
        description=(
            f"目录中 {len(missing)} 个条目在正文找不到对应标题，如：{sample}"
        ),
        rule_id="C1.toc_mismatch",
        category="content",
        is_problem=True,
        problem_type="目录正文不一致",
        rule_basis="依据《标准化工作导则 第1部分：标准化文件的结构和起草规则》（GB/T 1.1），目录中的各章、节标题应与正文标题完全一致",
        correction_suggestion=f"核对目录与正文标题，修正不一致的条目：{sample}",
    )]


def check_toc_page_overflow(toc_nav: "Any") -> list[Finding]:
    """C1.8 目录标注页码不得超出文档实际页数（需 TocNavigator）。

    典型问题：文档只有 547 页，目录却写了 "附录13……第557页"。
    说明目录页码与正文不一致，属于结构合规性缺陷。
    """
    try:
        overflow = toc_nav.overflow_entries()
    except Exception:
        return []
    if not overflow:
        return []

    total = toc_nav.total_pages
    findings: list[Finding] = []
    for entry in overflow[:5]:  # 最多报5条
        est_phys = entry.actual_page if entry.actual_page is not None else "?"
        findings.append(Finding(
            severity="medium",
            description=(
                f"目录条目【{entry.title[:30]}】标注第 {entry.stated_page} 页"
                f"（估算物理页 {est_phys}），超出文档实际页数 {total}"
            ),
            rule_id="C1.toc_page_overflow",
            category="content",
            is_problem=True,
            problem_type="目录页码溢出",
            rule_basis="依据《标准化工作导则 第1部分：标准化文件的结构和起草规则》（GB/T 1.1），目录页码应与正文实际页码一致",
            correction_suggestion=f"重新编排文档页码，或修正目录中的页码标注，确保与正文实际页数一致",
        ))
    if len(overflow) > 5:
        findings.append(Finding(
            severity="medium",
            description=f"共 {len(overflow)} 个目录条目页码超出文档实际页数 {total}",
            rule_id="C1.toc_page_overflow",
            category="content",
            is_problem=True,
            problem_type="目录页码溢出",
            rule_basis="依据《标准化工作导则 第1部分：标准化文件的结构和起草规则》（GB/T 1.1），目录页码应与正文实际页码一致",
            correction_suggestion="全面核查并修正目录页码，确保所有条目页码与正文实际页数一致",
        ))
    return findings


# ---------------------------------------------------------------------------
# Verdict 汇总
# ---------------------------------------------------------------------------


def derive_verdict(findings: list[Finding]) -> tuple[str, int, int]:
    if not findings:
        return "pass", 15, 95
    high = sum(1 for f in findings if f.severity == "high")
    medium = sum(1 for f in findings if f.severity == "medium")
    low = sum(1 for f in findings if f.severity == "low")

    if high > 0 or medium >= 3:
        return "fail", 5, 90
    if medium >= 1:
        return "partial", 10, 88
    return ("partial" if low > 0 else "pass"), 13, 85


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class C1StructureAgent(BaseAgent):
    """结构合规性 agent。纯规则，不调用 LLM。"""

    dimension = "C1_structure"

    # 所有检查项 rule_id（固定顺序，保证输出字段完整）
    RULE_IDS = [
        "C1.required_modules",
        "C1.hierarchy",
        "C1.title_length",
        "C1.key_appendix",
        "C1.appendix_content",
        "C1.appendix_continuity",
        "C1.toc_mismatch",
        "C1.toc_page_overflow",
    ]

    def run(self, chunks: list[dict[str, Any]], *, toc_nav: "Any | None" = None) -> AgentResult:
        facts = extract_structure(chunks)

        findings: list[Finding] = []
        findings += check_required_modules(facts)
        findings += check_hierarchical_numbering(facts)
        findings += check_title_conciseness(facts)
        findings += check_key_appendices(facts)
        findings += check_appendix_has_content(facts)
        findings += check_appendix_continuity(facts)
        findings += check_toc_vs_body(facts)
        if toc_nav is not None:
            findings += check_toc_page_overflow(toc_nav)

        verdict, score, confidence = derive_verdict(findings)
        details = self._build_details(facts, findings)

        result = AgentResult(
            dimension=self.dimension,
            verdict=verdict,
            score=score,
            confidence=confidence,
            findings=findings,
            details=details,
            extra={
                "structure_analysis": {
                    "heading_count": len(facts.headings),
                    "appendix_refs_count": len(facts.appendix_refs),
                    "appendix_sections": [
                        {
                            "label": s.label,
                            "title": s.title,
                            "has_content": s.has_content,
                            "section_path": s.section_path,
                            "paragraph_index": s.paragraph_index,
                        }
                        for s in facts.appendix_sections
                    ],
                    "toc_entries_count": len(facts.toc_titles),
                    "titles_sample": facts.all_titles[:10],
                },
            },
            need_human_review=False,
        )
        # 打标格式：每个检查项独立字段，带 evidence
        result.extra["label"] = result.to_label_dict(self.RULE_IDS)
        return result

    @staticmethod
    def _build_details(facts: StructureFacts, findings: list[Finding]) -> str:
        app_labels = [s.label for s in facts.appendix_sections]
        if not findings:
            return (
                f"识别到 {len(facts.headings)} 个标题，"
                f"附录章节 {app_labels}，"
                f"正文附录引用 {len(facts.appendix_refs)} 处，全部检查项通过。"
            )
        return (
            f"识别到 {len(facts.headings)} 个标题、"
            f"附录章节 {app_labels}、"
            f"正文附录引用 {len(facts.appendix_refs)} 处；"
            f"共 {len(findings)} 条问题（"
            f"high={sum(1 for f in findings if f.severity=='high')}, "
            f"medium={sum(1 for f in findings if f.severity=='medium')}, "
            f"low={sum(1 for f in findings if f.severity=='low')}）。"
        )
