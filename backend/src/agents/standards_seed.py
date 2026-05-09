"""向 SQLite 写入演示用标准条款，供 FTS + LLM 维度检索。

生产环境可改为从国标 Markdown/数据库批量导入；此处为最小可运行子集。
"""

from __future__ import annotations

from typing import Any

from src.store.repository import Repository

# (id, standard_name, clause_num, title, content, tags)
DEMO_STANDARDS: list[tuple[str, str, str, str, str, list[str]]] = [
    (
        "QSY1217_岗位职责",
        "QSY1217",
        "5.2",
        "岗位职责与安全环保",
        "作业区应明确各岗位职责，岗位职责描述中应包含安全环保责任条款，"
        "确保QHSE职责落实到人。操作规程应覆盖岗位条件、作业内容、风险辨识与应急处置要点。",
        ["C2_content_completeness", "E1_staffing"],
    ),
    (
        "QSY1217_应急",
        "QSY1217",
        "6.1",
        "应急与事故响应",
        "发生泄漏、火灾、爆炸等突发事件时，应启动应急预案，按规定的报告程序和现场处置顺序执行，"
        "现场抢险、警戒与恢复应有序衔接，不得颠倒关键处置步骤。",
        ["C2_content_completeness", "E2_emergency"],
    ),
    (
        "TSG31_规程",
        "TSG31",
        "3.2",
        "压力管道使用管理",
        "使用单位应建立健全操作规程，明确技术参数、操作步骤与安全注意事项；"
        "操作规程应真实反映设备与管道实际状态，关键参数不得与铭牌和设计文件矛盾。",
        ["C2_content_completeness"],
    ),
    (
        "GBT21246_天然气",
        "GBT21246",
        "4.1",
        "天然气输送系统",
        "天然气管道设计与运营应满足压力、温度、输量等技术参数的匹配要求，并在技术文件中完整表述。",
        ["C2_content_completeness"],
    ),
    (
        "AQ3057_处置",
        "AQ3057",
        "4.3",
        "现场应急处置",
        "应急处置应遵循先控制危险源、防止次生灾害扩大的原则；人员疏散、警戒设防、抢险作业顺序应符合国家有关现场处置规范。",
        ["E2_emergency"],
    ),
    (
        "GBT1.1_缩略词",
        "GBT1.1",
        "8.8",
        "语言文字与缩略词",
        "文档中首次出现的缩略词和符号应在中文全称或定义后给出注释；语句应通顺，标点符号使用应符合中文排版规范。",
        ["C3_language", "C4_reference"],
    ),
    (
        "GB32167_完整性",
        "GB32167",
        "5.1",
        "管道完整性数据",
        "油气输送管道完整性管理应覆盖数据采集、高后果区识别、检测与维修等活动，并与适用的国标、企标协调一致。",
        ["L2_standards"],
    ),
    (
        "QSY1217_逻辑一致",
        "QSY1217",
        "7.1",
        "文档逻辑与一致性",
        "技术文件中的参数、作业步骤顺序、时间与附件引用应一致，不得相互矛盾或与应急处置顺序冲突。",
        ["C5_logic"],
    ),
]


def ensure_demo_standards(repo: Repository) -> int:
    """幂等写入 DEMO_STANDARDS + 从 Markdown 导入真实条款 + 加载版本元数据。"""
    n = 0
    for row in DEMO_STANDARDS:
        clause_id, std, num, title, content, tags = row
        repo.upsert_standard(clause_id, std, num, title, content, tags)
        n += 1

    # 从 Markdown 文件导入真实标准条款（文件不存在则静默跳过）
    try:
        from src.standards_lib.md_importer import import_markdown_standards
        results = import_markdown_standards(repo)
        imported = sum(v for v in results.values() if v > 0)
        if imported:
            import logging
            logging.getLogger(__name__).info("从 Markdown 导入标准条款 %d 条", imported)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Markdown 标准导入失败（非致命）: %s", e)

    # 加载标准版本元数据
    try:
        from src.standards_lib.loader import load_versions_from_yaml
        load_versions_from_yaml(repo)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("版本元数据加载失败（非致命）: %s", e)

    return n


def demo_standards_for_prompt(dimension: str) -> list[dict[str, Any]]:
    """无 Repository 或检索无命中时给 LLM 的静态条款摘要。"""
    out: list[dict[str, Any]] = []
    for row in DEMO_STANDARDS:
        if dimension in row[5]:
            out.append(
                {
                    "id": row[0],
                    "standard_name": row[1],
                    "clause_num": row[2],
                    "title": row[3],
                    "content": row[4],
                }
            )
    return out
