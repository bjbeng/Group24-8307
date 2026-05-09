"""把标准 Markdown 文件 embed 后导入 ChromaDB pipeline_specs collection。

用于场景一原有 5 个标准（只有 FTS5，缺 ChromaDB）的补充导入。
切块策略与 md_importer 一致（按 # 标题切 section），
metadata 格式与 任务一 existing chunks 兼容。
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_MIN_CONTENT_CHARS = 60
_MAX_CONTENT_CHARS = 2000
_BATCH_SIZE = 16


# 标准号 → doc_type 映射
_DOC_TYPE_MAP = {
    "TSG":  "TSG",
    "AQ":   "AQ",
    "GBT":  "GB_T",
    "GB":   "GB",
    "QSY":  "Q_SY",
    "SYT":  "SY_T",
    "NBT":  "NB_T",
}


def _doc_type(standard_name: str) -> str:
    for prefix, dtype in _DOC_TYPE_MAP.items():
        if standard_name.upper().startswith(prefix):
            return dtype
    return "OTHER"


def _chunk_id(standard_name: str, idx: int) -> str:
    safe = re.sub(r"[^A-Za-z0-9一-鿿]", "_", standard_name)[:30]
    return f"{safe}_{idx:04d}"


def _parse_sections(md_text: str) -> list[dict[str, str]]:
    """按 # 标题切 section，返回 [{title, content, chapter}]。"""
    sections: list[dict[str, str]] = []
    current_title = ""
    current_chapter = ""
    lines: list[str] = []
    _TOC = {"目次", "目录", "contents", "table of contents"}

    def _flush():
        if not lines:
            return
        content = "\n".join(lines).strip()
        if len(content) >= _MIN_CONTENT_CHARS:
            sections.append({
                "title":   current_title,
                "content": content[:_MAX_CONTENT_CHARS],
                "chapter": current_chapter,
            })

    for line in md_text.splitlines():
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            _flush()
            lines = []
            current_title = m.group(2).strip()
            if any(kw in current_title.lower() for kw in _TOC):
                current_title = ""
                continue
            # 一级标题作为 chapter
            if len(m.group(1)) == 1:
                current_chapter = current_title
        elif current_title:
            lines.append(line)

    _flush()
    return sections


def _generate_summaries(
    sections: list[dict[str, str]],
    standard_name: str,
) -> list[tuple[str, str]]:
    """用 LLM 为每个 section 生成 prev_summary / next_summary。

    返回 [(prev_summary, next_summary), ...] 与 sections 等长。
    失败时返回空字符串对，不影响主流程。
    """
    try:
        import os, httpx, json as _json
        base_url = os.environ.get("LLM_BASE_URL", "http://localhost:8000/v1")
        api_key  = os.environ.get("LLM_API_KEY", "EMPTY")
        model    = os.environ.get("LLM_TEXT_MODEL", "deepseek-v3.2")
        headers  = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        results: list[tuple[str, str]] = [("", "")] * len(sections)
        texts = [s["content"] for s in sections]

        for idx, content in enumerate(texts):
            prev_content = texts[idx - 1][:300] if idx > 0 else ""
            next_content = texts[idx + 1][:300] if idx < len(texts) - 1 else ""
            prompt = (
                f"你是标准文档摘要专家。以下是标准《{standard_name}》中一个章节的内容。\n"
                f"请分别用不超过100字总结：①前文（上一节）的核心要点；②后文（下一节）的核心要点。\n"
                f"只输出JSON：{{\"prev_summary\": \"...\", \"next_summary\": \"...\"}}\n\n"
                f"前文内容：{prev_content or '（无）'}\n"
                f"本节内容：{content[:400]}\n"
                f"后文内容：{next_content or '（无）'}"
            )
            try:
                resp = httpx.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json={"model": model, "messages": [{"role": "user", "content": prompt}],
                          "max_tokens": 256, "temperature": 0.0},
                    timeout=30,
                )
                raw = resp.json()["choices"][0]["message"]["content"].strip()
                raw = raw.strip("```json").strip("```").strip()
                data = _json.loads(raw)
                results[idx] = (
                    str(data.get("prev_summary", "")),
                    str(data.get("next_summary", "")),
                )
            except Exception as e:
                log.debug("section %d summary 生成失败: %s", idx, e)

        log.info("%s: 生成 %d 条 summary", standard_name,
                 sum(1 for p, n in results if p or n))
        return results
    except Exception as e:
        log.warning("summary 批量生成失败，跳过: %s", e)
        return [("", "")] * len(sections)


def import_to_chroma(
    md_path: Path,
    standard_name: str,
    *,
    chroma_path: Path,
    collection_name: str = "pipeline_specs",
    force: bool = False,
    with_summaries: bool = True,
) -> int:
    """把一个 MD 文件 embed 后写入 ChromaDB。返回写入 chunk 数。"""
    try:
        import chromadb
        from src.standards_lib.embedder import get_embedder
    except ImportError as e:
        log.error("缺少依赖: %s", e)
        return 0

    client = chromadb.PersistentClient(path=str(chroma_path.resolve()))
    col = client.get_or_create_collection(
        collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    # 检查是否已导入（非 force 模式）
    if not force:
        existing = col.get(where={"source": standard_name}, limit=1)
        if existing["ids"]:
            log.debug("%s 已在 ChromaDB 中，跳过（force=False）", standard_name)
            return -1

    if not md_path.exists():
        log.warning("MD 文件不存在，跳过 %s: %s", standard_name, md_path)
        return 0

    md_text = md_path.read_text(encoding="utf-8")
    sections = _parse_sections(md_text)
    if not sections:
        log.warning("%s 解析出 0 个 section", standard_name)
        return 0

    embedder = get_embedder()
    doc_type = _doc_type(standard_name)

    # LLM 生成上下文摘要（可选，失败时静默降级为空字符串）
    summaries = _generate_summaries(sections, standard_name) if with_summaries else [("", "")] * len(sections)

    ids, documents, metadatas, embeddings_list = [], [], [], []

    for idx, sec in enumerate(sections):
        chunk_id = _chunk_id(standard_name, idx)
        prev_id = _chunk_id(standard_name, idx - 1) if idx > 0 else ""
        next_id = _chunk_id(standard_name, idx + 1) if idx < len(sections) - 1 else ""
        prev_summary, next_summary = summaries[idx]

        meta: dict[str, Any] = {
            "source":        standard_name,
            "chunk_type":    "text",
            "doc_type":      doc_type,
            "chapter":       sec["chapter"],
            "section":       sec["title"],
            "clause":        "",
            "is_mandatory":  "False",
            "obligation_level": "info",
            "has_table":     "False",
            "has_formula":   "False",
            "prev_chunk_id": prev_id,
            "next_chunk_id": next_id,
            "prev_summary":  prev_summary,
            "next_summary":  next_summary,
        }

        ids.append(chunk_id)
        documents.append(sec["content"])
        metadatas.append(meta)

    # 批量 embed
    texts = documents
    all_vecs = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i: i + _BATCH_SIZE]
        vecs = embedder.encode(batch)
        all_vecs.extend(vecs.tolist())

    # 批量写入 ChromaDB
    for i in range(0, len(ids), _BATCH_SIZE):
        col.upsert(
            ids=ids[i: i + _BATCH_SIZE],
            documents=documents[i: i + _BATCH_SIZE],
            metadatas=metadatas[i: i + _BATCH_SIZE],
            embeddings=all_vecs[i: i + _BATCH_SIZE],
        )

    log.info("✓ %s → ChromaDB %d chunks", standard_name, len(ids))
    return len(ids)


def import_scene1_to_chroma(
    scene1_dir: Path,
    chroma_path: Path,
    *,
    force: bool = False,
    with_summaries: bool = True,
) -> dict[str, int]:
    """把场景一 5 个原有标准补充导入 ChromaDB（含 LLM 上下文摘要）。"""
    specs = [
        ("TSG31",    scene1_dir / "MinerU_markdown_工业管道安全技术规程（TSG_31—2025）_2046287430936756224.md"),
        ("AQ3057",   scene1_dir / "MinerU_markdown_AQ3057—2025陆上油气长输管道建设项目安全预评价导则(10.64MB)_2046285873650397184.md"),
        ("GBT1.1",   scene1_dir / "MinerU_markdown_GBT1.1-2020标准化工作导则第1部分：标准化文件的结构和起草规则(13.52MB)_2046286981378666496.md"),
        ("GBT21246", scene1_dir / "MinerU_markdown_GBT21246-2020埋地钢质管道阴极保护参数测量方法(2.34MB)_2046287775037452288.md"),
        ("QSY1217",  scene1_dir / "MinerU_markdown_QSY1217-2009HSE作业指导书编写指南(4.87MB)_2046287470744891392.md"),
    ]
    results: dict[str, int] = {}
    for std_name, md_path in specs:
        results[std_name] = import_to_chroma(
            md_path, std_name, chroma_path=chroma_path,
            force=force, with_summaries=with_summaries,
        )
    return results
