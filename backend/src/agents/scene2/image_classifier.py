"""图片类型自动分类：把文档中提取的图片路由到对应 I1-I8 SubAgent。

当前策略（不调用大模型）：
1. 文件名/父目录关键词匹配（若文档有规范命名）
2. 上下文关键词匹配：section_path/title + 图片前后文本（更可靠）
3. 最后兜底：按顺序猜（仅在完全无关键词命中时使用）
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)

# classify_images 的 bucket 键（I* 前缀）→ VisionAgent.image_types / I2 必备图 使用的语义标签
S2_CLASSIFIER_LABEL_TO_SEMANTIC: dict[str, str] = {
    "I1_evacuation_route": "evacuation_route",
    "I2_assembly_point": "assembly_point",
    "I3_material": "emergency_assets",
    "I4_entry_route": "entry_route",
    "I5_hca_aerial": "hca_aerial",
    "I6_approval_page": "approval",
    # 与「市政管网交叉」示意图不同类，仅占位供 I7 有输入；若赛题区分更细可再拆类型
    "I7_pipeline_route": "municipal_crossing",
    # 直接使用语义标签，便于 I2 必备图统计命中
    "water_containment": "water_containment",
    "site_photo": "site_photo",
}


def map_classifier_label_to_agent_image_type(classifier_label: str) -> str:
    """将 classify_images 输出的标签转为各 scene2 Agent 期望的 ``image_type``。"""
    return S2_CLASSIFIER_LABEL_TO_SEMANTIC.get(classifier_label, classifier_label)

# 文件名/父目录关键词 → 图片类型
_FILENAME_KEYWORDS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"疏散|evacuation|escape", re.I), "I1_evacuation_route"),
    (re.compile(r"集合[点地]|assembly", re.I),     "I2_assembly_point"),
    (re.compile(r"物资|material|equipment", re.I),  "I3_material"),
    (re.compile(r"进场|entry|access|入场", re.I),   "I4_entry_route"),
    (re.compile(r"影像|aerial|卫星|航拍|satellite", re.I), "I5_hca_aerial"),
    (re.compile(r"签字|签批|审批|approval|sign", re.I), "I6_approval_page"),
    (re.compile(r"管道|pipeline|走向|route_map", re.I), "I7_pipeline_route"),
    (re.compile(r"围油|围堰|拦油|water|containment", re.I), "water_containment"),
    (re.compile(r"现场图|现场照片|site[_ -]?photo|photo", re.I), "site_photo"),
]

# 默认顺序（当文件名无法判断时，按提取顺序猜）
_DEFAULT_ORDER = [
    "I1_evacuation_route",
    "I4_entry_route",
    "I2_assembly_point",
    "site_photo",
    "I3_material",
    "I5_hca_aerial",
    "I6_approval_page",
]


def classify_images(
    image_paths: list[str | Path],
    *,
    context_by_path: dict[str, str] | None = None,
    context_meta_by_path: dict[str, dict[str, Any]] | None = None,
) -> dict[str, list[str]]:
    """
    把图片路径列表分类为 {image_type: [path, ...]} 字典。

    返回示例：
    {
        "I1_evacuation_route": ["path/img_0001.png"],
        "I6_approval_page":    ["path/img_0007.jpg"],
        "unknown":             ["path/img_0004.png"],
    }
    """
    result: dict[str, list[str]] = {}

    for i, path in enumerate(image_paths):
        p = Path(path)
        img_type = _classify_by_filename(p)
        if img_type != "unknown":
            log.info("图片分类[%s]: filename-hit → %s", p.name, img_type)

        # 文件名无法判断 → 用上下文关键词匹配（不调 LLM）
        if img_type == "unknown":
            meta = {}
            if context_meta_by_path:
                meta = context_meta_by_path.get(str(p.resolve())) or context_meta_by_path.get(str(p)) or {}
            ctx = ""
            if context_by_path:
                ctx = context_by_path.get(str(p.resolve())) or context_by_path.get(str(p)) or ""
            ctx_pred = _classify_by_context(ctx, meta=meta)
            if ctx_pred != "unknown":
                img_type = ctx_pred
                log.info("图片分类[%s]: context-hit → %s", p.name, img_type)

        # 还是 unknown → 按顺序猜
        if img_type == "unknown" and i < len(_DEFAULT_ORDER):
            img_type = _DEFAULT_ORDER[i]
            log.warning("图片分类[%s]: fallback-order[%d] → %s", p.name, i, img_type)

        result.setdefault(img_type, []).append(str(p))

    log.info("图片分类完成: %s", {k: len(v) for k, v in result.items()})
    return result


def _classify_by_filename(path: Path) -> str:
    """用文件名和父目录名匹配关键词。"""
    target = (path.stem + " " + path.parent.name).lower()
    for pattern, img_type in _FILENAME_KEYWORDS:
        if pattern.search(target):
            return img_type
    return "unknown"

# ------------------------------
# 上下文关键词分类（不调用大模型）
# ------------------------------

_CTX_KEYWORDS: dict[str, tuple[str, ...]] = {
    # 这些关键词来自你提到的 qzq_addwork2 版本，适配 scene2 semantic
    "I6_approval_page": (
        "签字", "审批", "评审意见", "签发意见",
        "编制", "校对", "审核", "批准", "批准人", "评审组长",
    ),
    "I5_hca_aerial": (
        "影像图", "高后果区影像", "周边建筑", "潜在影响",
        "影响半径", "管道周边", "航拍", "卫星",
    ),
    "I1_evacuation_route": (
        "逃生", "疏散方向", "应急疏散", "疏散路线", "疏散",
    ),
    "I2_assembly_point": (
        "集结点", "集合点", "应急疏散集结点", "集结",
    ),
    "I4_entry_route": (
        "入场", "进场", "应急救援路线", "应急入场", "救援路线",
    ),
    "I3_material": (
        "应急物资", "物资存放", "应急仓库", "阀室应急柜",
        "应急柜", "物资储备", "物资",
    ),
    "I7_pipeline_route": (
        "市政管网", "管网交叉", "交叉点", "穿越铁路", "穿越公路",
        "管线交叉", "市政",
    ),
    "water_containment": (
        "围油", "拦油", "围堰", "围油栏", "水体敏感", "围油设施",
    ),
    "site_photo": (
        "现场图", "现场照片", "标志桩", "管道现场", "现场踏勘",
    ),
}

_CTX_PRIORITY: dict[str, int] = {
    "I6_approval_page": 0,
    "I2_assembly_point": 1,
    "I1_evacuation_route": 2,
    "I5_hca_aerial": 3,
    "I7_pipeline_route": 4,
    "I4_entry_route": 5,
    "I3_material": 6,
    "water_containment": 7,
    "site_photo": 8,
    "unknown": 99,
}


def _hits(text: str, keywords: Iterable[str]) -> int:
    if not text:
        return 0
    return sum(1 for kw in keywords if kw and kw in text)


def _extract_context_fields(context: str, meta: dict[str, Any]) -> dict[str, str]:
    # 优先用结构化 meta；无 meta 时回退解析 context 字符串。
    section_path = str(meta.get("section_path", "") or "")
    title = str(meta.get("title", "") or "")
    prev_heading = str(meta.get("prev_heading", "") or "")
    prev_text = str(meta.get("prev_text", "") or "")
    next_heading = str(meta.get("next_heading", "") or "")
    next_text = str(meta.get("next_text", "") or "")
    if not any((section_path, title, prev_heading, prev_text, next_heading, next_text)) and context:
        for raw in context.splitlines():
            line = raw.strip()
            if line.startswith("section_path:"):
                section_path = line.split(":", 1)[1].strip()
            elif line.startswith("title:"):
                title = line.split(":", 1)[1].strip()
            elif line.startswith("prev_heading:"):
                prev_heading = line.split(":", 1)[1].strip()
            elif line.startswith("prev_text:"):
                prev_text = line.split(":", 1)[1].strip()
            elif line.startswith("next_heading:"):
                next_heading = line.split(":", 1)[1].strip()
            elif line.startswith("next_text:"):
                next_text = line.split(":", 1)[1].strip()
    return {
        "section_path": section_path,
        "title": title,
        "prev_heading": prev_heading,
        "prev_text": prev_text,
        "next_heading": next_heading,
        "next_text": next_text,
    }


def _classify_by_context(context: str, *, meta: dict[str, Any] | None = None) -> str:
    meta = meta or {}
    fields = _extract_context_fields(context, meta)
    if not any(fields.values()):
        return "unknown"

    # section/title 通常更接近图片语义，赋更高权重，减少跨段“物资”误吸附。
    weight_section = 3
    weight_prev = 2
    weight_next = 1

    section_blob = "\n".join([fields["section_path"], fields["title"]])
    prev_blob = "\n".join([fields["prev_heading"], fields["prev_text"]])
    next_blob = "\n".join([fields["next_heading"], fields["next_text"]])

    scores: dict[str, int] = {}
    for t, kws in _CTX_KEYWORDS.items():
        s = (
            _hits(section_blob, kws) * weight_section
            + _hits(prev_blob, kws) * weight_prev
            + _hits(next_blob, kws) * weight_next
        )
        if s > 0:
            scores[t] = s
    if not scores:
        return "unknown"
    best = sorted(scores.items(), key=lambda kv: (-kv[1], _CTX_PRIORITY.get(kv[0], 50)))
    return best[0][0]
