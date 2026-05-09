"""把 DocxBlock 流转为 Chunk 列表。

切块原则（与 system_design.md 4.1 一致）：
- 主切点：Heading 1/2/3
- 次切点：累积超过 max_tokens 时按段落断
- 表格：>10 行切独立 TABLE chunk（生成 SUMMARY + FULL 双版本）；≤10 行内嵌父 chunk
- 图片：永远独立成块；父 chunk 用占位符引用
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.parse.docx_parser import DocxBlock, DocxBlockType

from .models import Chunk, ChunkType


_DEFAULT_MAX_TOKENS = 800
_DEFAULT_TABLE_INLINE_ROWS = 10
_TOKEN_RATIO = 1.4   # 中文：1 字符 ≈ 1.4 token；保守估算


def _est_tokens(text: str) -> int:
    return int(len(text) * _TOKEN_RATIO)


def _section_from_heading(heading_text: str, parent_path: str, level: int) -> str:
    """从标题文字推断 section_path。

    支持格式：
    - "1. 标题" → "1"
    - "2.1 标题" → "2.1"
    - "2.1. 1.1  站场通用设计" → "2.1" （去掉额外的前缀）
    - "2.1.1. **1.1.1  站场布置要求**" → "2.1.1"
    - "附录A" → "APP_A"
    """
    # 去掉 ** 粗体标记
    clean_text = re.sub(r'\*+', '', heading_text).strip()

    # 匹配：数字段（1 或 1.2 或 1.2.3 最多4层）+ 可选空格
    m = re.match(r'^(\d+(?:\.\d+){0,4})\.?\s+', clean_text)
    if m:
        return m.group(1)

    # 附录格式
    m = re.match(r'^附\s*[录件]\s*([A-Za-z0-9一二三四五六七八九十]+)', clean_text)
    if m:
        return f"APP_{m.group(1)}"

    # 无有效编号：用 heading level 推断
    if not parent_path:
        return f"H{level}_{clean_text[:8]}"

    return f"{parent_path}.x"


@dataclass
class _SectionState:
    path: str = ""
    title: str = ""
    level: int = 0


def chunk_docx_blocks(
    blocks: list[DocxBlock],
    doc_id: str,
    *,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    table_inline_rows: int = _DEFAULT_TABLE_INLINE_ROWS,
) -> list[Chunk]:
    """主入口。"""
    chunks: list[Chunk] = []
    section_stack: list[_SectionState] = [_SectionState(path="", title="(root)", level=0)]
    seq_counters: dict[tuple[str, str], int] = {}

    def _next_id(section_path: str, kind: str) -> str:
        key = (section_path, kind)
        seq_counters[key] = seq_counters.get(key, 0) + 1
        path_token = section_path or "ROOT"
        return f"{doc_id}__{path_token}__{kind}__{seq_counters[key]:03d}"

    pending_text: list[DocxBlock] = []

    def _flush_text() -> None:
        if not pending_text:
            return
        merged = "\n".join(b.text for b in pending_text)
        if not merged.strip():
            pending_text.clear()
            return
        section = section_stack[-1]
        first = pending_text[0]
        chunks.append(
            Chunk(
                chunk_id=_next_id(section.path, "text"),
                doc_id=doc_id,
                chunk_type=ChunkType.TEXT,
                section_path=section.path,
                title=section.title,
                content=merged,
                paragraph_index=first.paragraph_index,
                anchor_text=first.anchor_text or _make_anchor_from_text(merged),
                page_start=first.page_number,
                page_end=pending_text[-1].page_number,
                word_count=len(merged),
            )
        )
        pending_text.clear()

    for blk in blocks:
        if blk.block_type == DocxBlockType.HEADING:
            _flush_text()
            level = blk.heading_level or 1
            while section_stack and section_stack[-1].level >= level:
                section_stack.pop()
            parent_path = section_stack[-1].path if section_stack else ""
            section_path = _section_from_heading(blk.text, parent_path, level)
            new_state = _SectionState(path=section_path, title=blk.text, level=level)
            section_stack.append(new_state)
            chunks.append(
                Chunk(
                    chunk_id=_next_id(section_path, "heading"),
                    doc_id=doc_id,
                    chunk_type=ChunkType.HEADING,
                    section_path=section_path,
                    title=blk.text,
                    content=blk.text,
                    paragraph_index=blk.paragraph_index,
                    anchor_text=blk.anchor_text,
                    page_start=blk.page_number,
                    page_end=blk.page_number,
                    word_count=len(blk.text),
                )
            )
            continue

        if blk.block_type == DocxBlockType.PARAGRAPH:
            pending_text.append(blk)
            current = "\n".join(b.text for b in pending_text)
            if _est_tokens(current) >= max_tokens:
                _flush_text()
            continue

        if blk.block_type == DocxBlockType.TABLE:
            _flush_text()
            section = section_stack[-1]
            n_rows = len(blk.table_rows)
            if n_rows <= table_inline_rows:
                chunks.append(
                    Chunk(
                        chunk_id=_next_id(section.path, "table"),
                        doc_id=doc_id,
                        chunk_type=ChunkType.TABLE_SUMMARY,
                        section_path=section.path,
                        title=section.title,
                        content=blk.text,
                        paragraph_index=blk.paragraph_index,
                        anchor_text=blk.anchor_text,
                        page_start=blk.page_number,
                        page_end=blk.page_number,
                        word_count=len(blk.text),
                        extra={"rows": n_rows},
                    )
                )
            else:
                summary_lines = blk.table_rows[:4]
                summary_md = "\n".join("| " + " | ".join(r) + " |" for r in summary_lines)
                summary_md += f"\n... 共 {n_rows} 行"
                summary_id = _next_id(section.path, "table")
                full_id = summary_id + "__full"
                chunks.append(
                    Chunk(
                        chunk_id=summary_id,
                        doc_id=doc_id,
                        chunk_type=ChunkType.TABLE_SUMMARY,
                        section_path=section.path,
                        title=section.title,
                        content=summary_md,
                        paragraph_index=blk.paragraph_index,
                        anchor_text=blk.anchor_text,
                        page_start=blk.page_number,
                        page_end=blk.page_number,
                        word_count=len(summary_md),
                        cross_refs=[full_id],
                        extra={"rows": n_rows},
                    )
                )
                chunks.append(
                    Chunk(
                        chunk_id=full_id,
                        doc_id=doc_id,
                        chunk_type=ChunkType.TABLE_FULL,
                        section_path=section.path,
                        title=section.title,
                        content=blk.text,
                        paragraph_index=blk.paragraph_index,
                        anchor_text=blk.anchor_text,
                        page_start=blk.page_number,
                        page_end=blk.page_number,
                        word_count=len(blk.text),
                        parent_id=summary_id,
                        extra={"rows": n_rows},
                    )
                )
            continue

        if blk.block_type == DocxBlockType.IMAGE:
            _flush_text()
            section = section_stack[-1]
            cid = _next_id(section.path, "img")
            chunks.append(
                Chunk(
                    chunk_id=cid,
                    doc_id=doc_id,
                    chunk_type=ChunkType.IMAGE,
                    section_path=section.path,
                    title=section.title,
                    content=f"[IMAGE rid={blk.image_rid}]",
                    paragraph_index=blk.paragraph_index,
                    anchor_text=blk.anchor_text,
                    page_start=blk.page_number,
                    page_end=blk.page_number,
                    word_count=0,
                    extra={
                        "image_path": str(blk.image_path) if blk.image_path else None,
                        "image_rid": blk.image_rid,
                    },
                )
            )
            continue

    _flush_text()
    return chunks


def _make_anchor_from_text(text: str, max_len: int = 30) -> str:
    cleaned = re.sub(r"\s+", "", text)
    return cleaned[:max_len]


# ---------------------------------------------------------------------------
# MinerU ParsedBlock → Chunk（带精确 bbox 坐标）
# ---------------------------------------------------------------------------


def chunk_parsed_blocks(
    blocks: "list[Any]",
    doc_id: str,
    *,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
) -> list[Chunk]:
    """把 MinerU ParsedBlock 流转为 Chunk 列表，每个 chunk 携带 bbox 坐标。

    切分策略：
    1. 在 heading_level 1/2/3 处切分
    2. 文本段累积超过 max_tokens 时按段落断开
    3. 表格和图片各自独立成块
    """
    from src.parse.mineru_parser import ParsedBlock

    chunks: list[Chunk] = []
    section_stack: list[_SectionState] = [_SectionState(path="", title="(root)", level=0)]
    seq_counters: dict[tuple[str, str], int] = {}

    def _next_id(section_path: str, kind: str) -> str:
        key = (section_path, kind)
        seq_counters[key] = seq_counters.get(key, 0) + 1
        path_token = section_path or "ROOT"
        return f"{doc_id}__{path_token}__{kind}__{seq_counters[key]:03d}"

    pending: list[ParsedBlock] = []

    def _flush() -> None:
        if not pending:
            return
        merged = "\n".join(b.text for b in pending)
        if not merged.strip():
            pending.clear()
            return
        section = section_stack[-1]
        first = pending[0]
        chunks.append(Chunk(
            chunk_id=_next_id(section.path, "text"),
            doc_id=doc_id,
            chunk_type=ChunkType.TEXT,
            section_path=section.path,
            title=section.title,
            content=merged,
            paragraph_index=0,
            anchor_text=_make_anchor_from_text(merged),
            page_start=first.page_number,
            page_end=pending[-1].page_number,
            bbox=first.bbox,
            word_count=len(merged),
        ))
        pending.clear()

    for blk in blocks:
        if not isinstance(blk, ParsedBlock):
            continue

        if blk.block_type == "heading":
            _flush()
            level = blk.heading_level or 1
            while section_stack and section_stack[-1].level >= level:
                section_stack.pop()
            parent_path = section_stack[-1].path if section_stack else ""
            section_path = _section_from_heading(blk.text, parent_path, level)
            section_stack.append(_SectionState(path=section_path, title=blk.text, level=level))

            # NOTE: MinerU 3.1.6 office backend bug — all headings report
            # page_idx=3 regardless of their actual page. Workaround: use the
            # last pending text block's page number when available, otherwise
            # fall back to blk.page_number.
            prev_page = pending[-1].page_number if pending else blk.page_number

            chunks.append(Chunk(
                chunk_id=_next_id(section_path, "heading"),
                doc_id=doc_id,
                chunk_type=ChunkType.HEADING,
                section_path=section_path,
                title=blk.text,
                content=blk.text,
                paragraph_index=0,
                anchor_text=_make_anchor_from_text(blk.text),
                page_start=prev_page,
                page_end=prev_page,
                bbox=blk.bbox,
                word_count=len(blk.text),
            ))
            continue

        if blk.block_type == "text":
            pending.append(blk)
            if _est_tokens("\n".join(b.text for b in pending)) >= max_tokens:
                _flush()
            continue

        if blk.block_type == "table":
            _flush()
            section = section_stack[-1]
            # 把 HTML 表格转成简单文本摘要
            import re as _re
            cell_texts = _re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", blk.table_html or "", _re.S)
            table_text = " | ".join(t.strip() for t in cell_texts[:20])
            chunks.append(Chunk(
                chunk_id=_next_id(section.path, "table"),
                doc_id=doc_id,
                chunk_type=ChunkType.TABLE_SUMMARY,
                section_path=section.path,
                title=section.title,
                content=table_text or "[table]",
                paragraph_index=0,
                anchor_text=_make_anchor_from_text(table_text),
                page_start=blk.page_number,
                page_end=blk.page_number,
                bbox=blk.bbox,
                word_count=len(table_text),
                extra={"table_html": blk.table_html},
            ))
            continue

        if blk.block_type == "image":
            _flush()
            section = section_stack[-1]
            chunks.append(Chunk(
                chunk_id=_next_id(section.path, "img"),
                doc_id=doc_id,
                chunk_type=ChunkType.IMAGE,
                section_path=section.path,
                title=section.title,
                content=blk.text or "[image]",
                paragraph_index=0,
                anchor_text=_make_anchor_from_text(blk.text or "image"),
                page_start=blk.page_number,
                page_end=blk.page_number,
                bbox=blk.bbox,
                word_count=0,
                extra={"image_path": blk.image_path},
            ))
            continue

    _flush()
    return chunks
