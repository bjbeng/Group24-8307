"""一次性把全部 13 个标准导入 ChromaDB（含 LLM prev/next summary）。

用法：python -m src.cli ingest-chroma [--force]
"""
from __future__ import annotations

import logging
import os

import chromadb
from pathlib import Path

from src.llm import Message
from src.llm.factory import build_provider
from src.standards_lib.embedder import get_embedder
from src.store.repository import Repository

log = logging.getLogger(__name__)

_BATCH_SIZE = 16
_MAX_CONTENT = 2000

_DOC_TYPE_MAP = {
    "TSG": "TSG", "AQ": "AQ", "GBT": "GB_T",
    "GB": "GB", "QSY": "Q_SY", "SYT": "SY_T",
    "NBT": "NB_T",
}


def _doc_type(name: str) -> str:
    for p, t in _DOC_TYPE_MAP.items():
        if name.upper().startswith(p):
            return t
    return "OTHER"


def _chunk_id(name: str, idx: int) -> str:
    safe = name[:30].replace(" ", "_")
    return f"{safe}_{idx:04d}"


def _parse_sections(md_path: Path) -> list[dict]:
    text = md_path.read_text(encoding="utf-8")
    sections, cur_title, cur_chapter, lines = [], "", "", []
    TOC = {"目次", "目录", "contents", "table of contents"}

    def flush():
        if lines:
            c = "\n".join(lines).strip()
            if len(c) >= 60:
                sections.append({"title": cur_title, "content": c[:_MAX_CONTENT], "chapter": cur_chapter})
            lines.clear()

    for line in text.splitlines():
        m = __import__("re").match(r"^(#{1,4})\s+(.*)", line)
        if m:
            flush()
            cur_title = m.group(2).strip()
            if any(k in cur_title.lower() for k in TOC):
                cur_title = ""
                continue
            if len(m.group(1)) == 1:
                cur_chapter = cur_title
        elif cur_title:
            lines.append(line)
    flush()
    return sections


def _make_summaries(
    sections: list[dict],
    std_name: str,
    provider, text_model: str,
) -> list[tuple[str, str]]:
    results = [("", "")] * len(sections)
    for idx, sec in enumerate(sections):
        prev_c = sections[idx - 1]["content"][:300] if idx > 0 else ""
        next_c = sections[idx + 1]["content"][:300] if idx < len(sections) - 1 else ""
        prompt = (
            f"你是标准《{std_name}》章节摘要专家。只输出JSON：{{\"prev\":\"前文不超过80字\",\"next\":\"后文不超过80字\"}}\n"
            f"前文：{prev_c or '无'}\n当前：{sec['content'][:400]}\n后文：{next_c or '无'}"
        )
        try:
            raw = provider.call_text(
                [Message(role="user", content=prompt)],
                model=text_model, temperature=0.0, max_tokens=200,
            )
            import json
            data = json.loads(raw.strip().strip("```json").strip("```").strip())
            results[idx] = (str(data.get("prev", "")), str(data.get("next", "")))
        except Exception as e:
            log.warning("summary %s[%d] fail: %s", std_name, idx, e)
    return results


def _upsert_batch(col, ids, docs, metas, embs):
    for i in range(0, len(ids), _BATCH_SIZE):
        col.upsert(
            ids=ids[i:i+_BATCH_SIZE],
            documents=docs[i:i+_BATCH_SIZE],
            metadatas=metas[i:i+_BATCH_SIZE],
            embeddings=embs[i:i+_BATCH_SIZE],
        )


def ingest_all(force: bool = False) -> dict[str, int]:
    # 加载 .env 读取 LLM_BASE_URL / LLM_API_KEY
    _env_path = Path(__file__).resolve().parents[2] / ".env"
    from dotenv import load_dotenv
    load_dotenv(_env_path, override=False)

    chroma_env = os.environ.get("CHROMA_DB_PATH", "")
    if chroma_env:
        chroma_path = Path(chroma_env)
    else:
        chroma_path = Path(__file__).resolve().parents[2] / "data" / "chroma_db"
    if not chroma_path.is_absolute():
        chroma_path = Path(__file__).resolve().parents[2] / chroma_path
    chroma_path.parent.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(chroma_path.resolve()))
    col = client.get_or_create_collection("pipeline_specs", metadata={"hnsw:space": "cosine"})

    embedder = get_embedder()
    from src.config import get_default_config
    cfg = get_default_config()
    provider = build_provider(cfg)
    text_model = cfg.get("llm", {}).get("text_model", "deepseek-v3.2")

    scene1 = Path("D:/HKU-ds/8307NLP/project8307/场景一")
    task1 = scene1 / "场景一标准文件chunk" / "任务一"

    specs = [
        # scene1
        ("TSG31",    scene1 / "MinerU_markdown_工业管道安全技术规程（TSG_31—2025）_2046287430936756224.md"),
        ("AQ3057",   scene1 / "MinerU_markdown_AQ3057—2025陆上油气长输管道建设项目安全预评价导则(10.64MB)_2046285873650397184.md"),
        ("GBT1.1",   scene1 / "MinerU_markdown_GBT1.1-2020标准化工作导则第1部分：标准化文件的结构和起草规则(13.52MB)_2046286981378666496.md"),
        ("GBT21246", scene1 / "MinerU_markdown_GBT21246-2020埋地钢质管道阴极保护参数测量方法(2.34MB)_2046287775037452288.md"),
        ("QSY1217",  scene1 / "MinerU_markdown_QSY1217-2009HSE作业指导书编写指南(4.87MB)_2046287470744891392.md"),
        # task1
        ("GB50251",  task1 / "MinerU_markdown_GB_50251-2015_输气管道工程设计规范_2046645005091926016.md"),
        ("GB50253",  task1 / "MinerU_markdown_GB_50253-2014_输油管道工程设计规范_2046645051623534592.md"),
        ("GBT21447", task1 / "MinerU_markdown_GB-21447-2018-T钢质管道外腐蚀控制规范(1.52MB)_2046645122490499072.md"),
        ("GBT21448", task1 / "MinerU_markdown_GB-21448-2017-T埋地钢质管道阴极保护技术规范(2.7MB)_2046645103494496256.md"),
        ("SYT5922",  task1 / "MinerU_markdown_SYT5922-2024天然气管道运行规范(8.58MB)_2046645169470898176.md"),
        ("SYT6069",  task1 / "MinerU_markdown_SYT6069-2020油气管道仪表及自动化系统运行技术规范(9.54MB)_2046645150797856768.md"),
        ("GBT19023", task1 / "MinerU_markdown_GBT19023-2025dz_2046645290120048640.md"),
        ("GBT25000.51", task1 / "MinerU_markdown_GBT_25000.51-2016_系统与软件工程_系统与软件质量要求和评价_2046645081004634112.md"),
    ]

    results = {}
    for std_name, md_path in specs:
        if not md_path.exists():
            log.warning("SKIP %s: %s not found", std_name, md_path)
            results[std_name] = 0
            continue
        if not force:
            existing = col.get(where={"source": std_name}, limit=1)
            if existing["ids"]:
                log.info("SKIP %s: already in chroma", std_name)
                results[std_name] = -1
                continue

        log.info("Processing %s ...", std_name)
        sections = _parse_sections(md_path)
        log.info("  %d sections parsed", len(sections))
        summaries = _make_summaries(sections, std_name, provider, text_model)
        log.info("  %d summaries generated", sum(1 for p, n in summaries if p or n))

        doc_type = _doc_type(std_name)
        ids, docs, metas, embs = [], [], [], []
        for idx, sec in enumerate(sections):
            cid = _chunk_id(std_name, idx)
            prev_s, next_s = summaries[idx]
            meta = {
                "source": std_name, "chunk_type": "text", "doc_type": doc_type,
                "chapter": sec["chapter"], "section": sec["title"], "clause": "",
                "is_mandatory": "False", "obligation_level": "info",
                "has_table": "False", "has_formula": "False",
                "prev_chunk_id": _chunk_id(std_name, idx - 1) if idx > 0 else "",
                "next_chunk_id": _chunk_id(std_name, idx + 1) if idx < len(sections) - 1 else "",
                "prev_summary": prev_s, "next_summary": next_s,
            }
            ids.append(cid); docs.append(sec["content"]); metas.append(meta)

        all_vecs = []
        for i in range(0, len(ids), _BATCH_SIZE):
            vecs = embedder.encode(docs[i:i+_BATCH_SIZE])
            all_vecs.extend(vecs.tolist())

        _upsert_batch(col, ids, docs, metas, all_vecs)
        log.info("  upserted %d chunks", len(ids))
        results[std_name] = len(ids)

    log.info("TOTAL: %d chunks in chroma", col.count())
    return results