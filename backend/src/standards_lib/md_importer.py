"""把 MinerU 生成的标准 Markdown 文件切块后导入 standards FTS5 表。

每个 `#`/`##`/`###` 标题 + 其正文构成一个条款记录。
TOC 段（目次/目录）自动跳过。
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.store.repository import Repository

log = logging.getLogger(__name__)

# 跳过的章节关键词（目录不计入条款）
_TOC_KEYWORDS = {"目次", "目录", "contents", "table of contents"}

# 维度关键词映射（按优先级排序；一个条款可打多个 tag）
_DIM_KEYWORDS: list[tuple[str, list[str]]] = [
    ("E2_emergency",             ["应急", "处置", "事故", "泄漏", "预案", "响应", "警戒", "疏散"]),
    ("E1_staffing",              ["岗位", "人员", "培训", "资质", "任职", "职称", "考核"]),
    ("C3_language",              ["语言", "术语", "定义", "缩略", "标点", "用语", "注释"]),
    ("C1_structure",             ["目录", "章节", "标题", "附录", "索引", "编号", "层级"]),
    ("C5_logic",                 ["一致", "矛盾", "前后", "不得", "禁止", "必须", "应与"]),
    ("L2_standards",             ["GB", "QSY", "TSG", "AQ", "引用", "规范性引用", "版本"]),
    ("C2_content_completeness",  ["职责", "岗位", "操作", "规程", "参数", "安全", "HSE", "QHSE"]),
]

# 段落最小长度（太短的条款噪音多，跳过）
_MIN_CONTENT_CHARS = 60


@dataclass
class _Section:
    level: int
    title: str
    lines: list[str] = field(default_factory=list)

    @property
    def content(self) -> str:
        return "\n".join(self.lines).strip()


def _parse_sections(md_text: str) -> list[_Section]:
    """把 Markdown 按标题切成 Section 列表，跳过 TOC。"""
    sections: list[_Section] = []
    current: _Section | None = None
    in_toc = False

    for line in md_text.splitlines():
        heading_m = re.match(r"^(#{1,4})\s+(.*)", line)
        if heading_m:
            if current is not None and not in_toc:
                sections.append(current)
            level = len(heading_m.group(1))
            title = heading_m.group(2).strip()
            in_toc = any(kw in title.lower() for kw in _TOC_KEYWORDS)
            current = _Section(level=level, title=title)
        elif current is not None and not in_toc:
            current.lines.append(line)

    if current is not None and not in_toc:
        sections.append(current)

    return sections


def _assign_tags(title: str, content: str, default_tags: list[str]) -> list[str]:
    blob = title + " " + content
    tags = list(default_tags)
    for dim, keywords in _DIM_KEYWORDS:
        if dim not in tags and any(kw in blob for kw in keywords):
            tags.append(dim)
    return tags or ["C2_content_completeness"]


def _clause_id(standard_name: str, title: str, idx: int) -> str:
    h = hashlib.md5(f"{standard_name}|{title}|{idx}".encode()).hexdigest()[:8]
    safe_title = re.sub(r"[^A-Za-z0-9一-鿿]", "_", title)[:30]
    return f"{standard_name}_{safe_title}_{h}"


# ── 场景一五个标准的源文件配置 ──────────────────────────────────────────────

@dataclass
class _SourceSpec:
    standard_name: str   # 用于 FTS 检索白名单
    year: int
    md_path: Path
    default_tags: list[str]


def _build_sources(base_dir: Path) -> list[_SourceSpec]:
    """生成全部标准的导入配置。

    base_dir 指向 场景一/ 目录；任务一的 8 个标准在其子目录
    场景一标准文件chunk/任务一/ 下。
    """
    task1_dir = base_dir / "场景一标准文件chunk" / "任务一"
    return [
        # ── 场景一原有 5 个标准 ──────────────────────────────────────────
        _SourceSpec(
            standard_name="TSG31",
            year=2025,
            md_path=base_dir / "MinerU_markdown_工业管道安全技术规程（TSG_31—2025）_2046287430936756224.md",
            default_tags=["C2_content_completeness", "L2_standards"],
        ),
        _SourceSpec(
            standard_name="AQ3057",
            year=2025,
            md_path=base_dir / "MinerU_markdown_AQ3057—2025陆上油气长输管道建设项目安全预评价导则(10.64MB)_2046285873650397184.md",
            default_tags=["E2_emergency", "C2_content_completeness"],
        ),
        _SourceSpec(
            standard_name="GBT1.1",
            year=2020,
            md_path=base_dir / "MinerU_markdown_GBT1.1-2020标准化工作导则第1部分：标准化文件的结构和起草规则(13.52MB)_2046286981378666496.md",
            default_tags=["C1_structure", "C3_language"],
        ),
        _SourceSpec(
            standard_name="GBT21246",
            year=2020,
            md_path=base_dir / "MinerU_markdown_GBT21246-2020埋地钢质管道阴极保护参数测量方法(2.34MB)_2046287775037452288.md",
            default_tags=["C2_content_completeness"],
        ),
        _SourceSpec(
            standard_name="QSY1217",
            year=2009,
            md_path=base_dir / "MinerU_markdown_QSY1217-2009HSE作业指导书编写指南(4.87MB)_2046287470744891392.md",
            default_tags=["C1_structure", "C2_content_completeness", "E1_staffing"],
        ),
        # ── 任务一新增 8 个标准 ──────────────────────────────────────────
        _SourceSpec(
            standard_name="GB50251",
            year=2015,
            md_path=task1_dir / "MinerU_markdown_GB_50251-2015_输气管道工程设计规范_2046645005091926016.md",
            default_tags=["C2_content_completeness", "C5_logic", "L2_standards"],
        ),
        _SourceSpec(
            standard_name="GB50253",
            year=2014,
            md_path=task1_dir / "MinerU_markdown_GB_50253-2014_输油管道工程设计规范_2046645051623534592.md",
            default_tags=["C2_content_completeness", "C5_logic", "L2_standards"],
        ),
        _SourceSpec(
            standard_name="GBT21447",
            year=2018,
            md_path=task1_dir / "MinerU_markdown_GB-21447-2018-T钢质管道外腐蚀控制规范(1.52MB)_2046645122490499072.md",
            default_tags=["C2_content_completeness", "L2_standards"],
        ),
        _SourceSpec(
            standard_name="GBT21448",
            year=2017,
            md_path=task1_dir / "MinerU_markdown_GB-21448-2017-T埋地钢质管道阴极保护技术规范(2.7MB)_2046645103494496256.md",
            default_tags=["C2_content_completeness", "L2_standards"],
        ),
        _SourceSpec(
            standard_name="SYT5922",
            year=2024,
            md_path=task1_dir / "MinerU_markdown_SYT5922-2024天然气管道运行规范(8.58MB)_2046645169470898176.md",
            default_tags=["C2_content_completeness", "C5_logic", "E1_staffing", "E2_emergency"],
        ),
        _SourceSpec(
            standard_name="SYT6069",
            year=2020,
            md_path=task1_dir / "MinerU_markdown_SYT6069-2020油气管道仪表及自动化系统运行技术规范(9.54MB)_2046645150797856768.md",
            default_tags=["C2_content_completeness", "C5_logic", "L2_standards"],
        ),
        _SourceSpec(
            standard_name="GBT19023",
            year=2025,
            md_path=task1_dir / "MinerU_markdown_GBT19023-2025dz_2046645290120048640.md",
            default_tags=["C1_structure", "C3_language"],
        ),
        _SourceSpec(
            standard_name="GBT25000.51",
            year=2016,
            md_path=task1_dir / "MinerU_markdown_GBT_25000.51-2016_系统与软件工程_系统与软件质量要求和评价_2046645081004634112.md",
            default_tags=["C1_structure"],
        ),
    ]


def import_markdown_standards(
    repo: Repository,
    md_dir: Path | str | None = None,
    *,
    force: bool = False,
) -> dict[str, int]:
    """导入五个标准 Markdown 到 standards FTS5 表。

    Args:
        repo: SQLite 数据访问对象
        md_dir: Markdown 文件目录；None 时使用 default.yaml 中 paths.data_dir 同级的场景一目录
        force: True 时重新导入（即使已存在）

    Returns:
        {standard_name: imported_clause_count}
    """
    if md_dir is None:
        # 默认路径：相对于 backend 根目录的 ../../场景一
        backend_root = Path(__file__).resolve().parent.parent.parent
        md_dir = backend_root.parent.parent / "场景一"

    md_dir = Path(md_dir)
    sources = _build_sources(md_dir)
    summary: dict[str, int] = {}

    for spec in sources:
        if not spec.md_path.exists():
            log.warning("Markdown 文件不存在，跳过 %s：%s", spec.standard_name, spec.md_path)
            summary[spec.standard_name] = 0
            continue

        # 检查是否已导入（非 force 模式）
        if not force:
            existing = repo.search_standards(
                spec.standard_name, standard_filter=[spec.standard_name], top_k=1
            )
            if existing:
                log.debug("%s 已在库中，跳过（force=False）", spec.standard_name)
                summary[spec.standard_name] = -1  # -1 表示"已存在，跳过"
                continue

        md_text = spec.md_path.read_text(encoding="utf-8")
        sections = _parse_sections(md_text)
        count = 0

        for idx, sec in enumerate(sections):
            content = sec.content
            if len(content) < _MIN_CONTENT_CHARS:
                continue

            tags = _assign_tags(sec.title, content, spec.default_tags)
            clause_id = _clause_id(spec.standard_name, sec.title, idx)
            # clause_num 从标题提取数字前缀（如 "3.2 设计要求" → "3.2"）
            num_m = re.match(r"^(\d+(?:\.\d+)*)\s", sec.title)
            clause_num = num_m.group(1) if num_m else ""

            try:
                repo.upsert_standard(
                    clause_id=clause_id,
                    standard_name=spec.standard_name,
                    clause_num=clause_num,
                    title=sec.title,
                    content=content[:2000],  # 单条款不超过 2000 字
                    tags=tags,
                )
                count += 1
            except Exception as e:
                log.warning("写入失败 %s/%s: %s", spec.standard_name, clause_id, e)

        log.info("✓ %s 导入 %d 条款", spec.standard_name, count)
        summary[spec.standard_name] = count

    return summary
