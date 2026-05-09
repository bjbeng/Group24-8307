"""ImageChunk 数据模型 —— 场景二多模态审核专用。

与 TextChunk(`Chunk`) 平行的数据结构：
- 文本块走 `chunks` 表，图片块走 `image_chunks` 表
- text_chunk 切块时遇到 IMAGE 类型，会同时产出一个 Chunk 占位（标记父章节归属）
  和一个 ImageChunk 实例
- description: VL 模型生成的自然语言摘要，可入 image_chunks_fts 检索
- analysis: 各 image_type 专属的结构化字段（如 approval 的 signatures、hca_aerial 的
  building_count 等），由 vision_pipeline 调用 VL 模型后填入
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


SUPPORTED_IMAGE_TYPES = (
    "approval",            # 签字审批页
    "hca_aerial",          # 高后果区影像图
    "evacuation_route",    # 逃生路线图
    "assembly_point",      # 应急疏散集结点
    "entry_route",         # 入场/进场路线图
    "emergency_assets",    # 应急物资点位
    "municipal_crossing",  # 市政管网交叉图
    "water_containment",   # 围油设施图
    "site_photo",          # 高后果区现场图
    "unknown",             # 分类失败
)


@dataclass
class ImageChunk:
    """单张图片的结构化表示。"""

    chunk_id: str
    doc_id: str
    image_type: str
    image_path: str
    parent_chunk_id: str | None = None
    section_path: str = ""
    title: str = ""
    description: str = ""
    analysis: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    paragraph_index: int = 0
    page_start: int | None = None

    def to_row(self) -> dict[str, Any]:
        """转换为 image_chunks 表 INSERT 用的 dict。"""
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "image_type": self.image_type,
            "image_path": self.image_path,
            "parent_chunk_id": self.parent_chunk_id,
            "description": self.description,
            "analysis": json.dumps(self.analysis, ensure_ascii=False),
        }
