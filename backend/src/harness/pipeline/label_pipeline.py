"""打标 Pipeline（Label）：Explorer A ‖ Explorer B → Critic → Ground Truth。

场景一：作业书（文本）
场景二：风险管控方案（文本 + 图片）
"""
from __future__ import annotations

import concurrent.futures
import datetime
import logging
import time
from pathlib import Path
from typing import Any

from src.agents.base import AgentResult
from src.agents.standards_seed import ensure_demo_standards
from src.chunk import chunk_docx_blocks
from src.config import get_default_config
from src.harness.agent_group.critic import CrossDimensionCritic
from src.harness.agent_group.explorer import ExplorerFactory
from src.harness.agent_group.sub_agent import Scenario
from src.harness.session.doc_session import DocSession
from src.llm import build_provider
from src.metrics import MetricsContext, compute_metrics
from src.parse import convert_doc_to_docx, parse_docx
from src.pipeline.audit import derive_doc_id
from src.store import Repository

log = logging.getLogger(__name__)


class LabelResult:
    def __init__(
        self,
        doc_id: str,
        doc_name: str,
        dimensions: dict[str, AgentResult],
        elapsed_seconds: float,
        scenario: Scenario,
    ) -> None:
        self.doc_id = doc_id
        self.doc_name = doc_name
        self.dimensions = dimensions
        self.elapsed_seconds = elapsed_seconds
        self.scenario = scenario

    @property
    def overall_verdict(self) -> str:
        verdicts = [result.verdict for result in self.dimensions.values()]
        if not verdicts:
            return "uncertain"
        if "fail" in verdicts:
            return "fail"
        if all(verdict == "pass" for verdict in verdicts):
            return "pass"
        if "uncertain" in verdicts:
            return "uncertain"
        return "partial"

    @property
    def overall_score(self) -> int:
        return sum(result.score or 0 for result in self.dimensions.values())

    @property
    def need_human_review(self) -> bool:
        return any(result.need_human_review for result in self.dimensions.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "doc_name": self.doc_name,
            "scenario": self.scenario,
            "pipeline": "label",
            "overall_verdict": self.overall_verdict,
            "overall_score": self.overall_score,
            "normalized_score": round(self.overall_score / 168 * 100) if self.scenario == "s2" else round(self.overall_score / 132 * 100),
            "max_score": 168 if self.scenario == "s2" else 132,
            "need_human_review": self.need_human_review,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "dimensions": {k: v.to_dict() for k, v in self.dimensions.items()},
        }


class LabelPipeline:
    """
    打标 Pipeline：
      A ‖ B（各自内部并发所有 sub-agents）
      → CrossDimensionCritic
      → 写入 labels 表（GT）
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        scenario: Scenario = "s1",
    ) -> None:
        self.config = config or get_default_config()
        self.scenario = scenario
        llm_cfg = self.config.get("llm", {}) or {}

        db_path = self.config["paths"]["db_path"]
        self.repo = Repository(db_path)
        ensure_demo_standards(self.repo)

        from src.llm.factory import build_provider_for_role
        critic_model = llm_cfg.get("critic", {}).get(
            "model", llm_cfg.get("text_model", "mock")
        )
        critic_provider = build_provider_for_role(self.config, "critic")

        self._factory = ExplorerFactory(
            config=self.config,
            repo=self.repo,
            scenario=scenario,
            max_workers=int(self.config.get("audit", {}).get("dim_concurrency", 8)),
        )
        self._critic = CrossDimensionCritic(
            provider=critic_provider,
            critic_model=critic_model,
            repo=self.repo,
        )
        self._session = DocSession(db_path)

        # 预热 Embedder（避免首次检索时 2-5 秒延迟）
        from src.standards_lib.embedder import preload_embedder
        preload_embedder()

    def run(self, doc_path: str | Path, progress_cb=None) -> LabelResult:
        t0 = time.perf_counter()
        path = Path(doc_path).resolve()
        doc_id = derive_doc_id(path)
        log.info("[Label] 开始打标 %s scenario=%s", path.name, self.scenario)

        # 解析
        chunks, image_chunks = self._ingest(path, doc_id)

        # 场景二：可选的图片 VL 预分析（会调用大模型）。
        # 你要求“去掉大模型判定”时，通常也希望这里默认不触发；因此改为显式开关。
        # 通过环境变量 INDUSTRY_ENABLE_VISION_ANALYSIS=1 才启用。
        import os as _os
        enable_vision_analysis = _os.environ.get("INDUSTRY_ENABLE_VISION_ANALYSIS", "").strip().lower() in {"1", "true", "yes", "on"}
        if self.scenario == "s2" and image_chunks and enable_vision_analysis:
            llm_cfg = self.config.get("llm", {}) or {}
            vision_model = (
                (llm_cfg.get("vision", {}) or {}).get("model")
                or llm_cfg.get("vision_model", "")
            )
            if not vision_model:
                log.warning("[Label s2] 未配置 llm.vision.model，跳过图片 VL 预分析（I* 维度可能缺少 analysis）")
            else:
                try:
                    from src.agents.scene2.vision_base import VisionAgent  # noqa: F401
                    from src.chunk.image_chunk import ImageChunk
                    from src.llm.factory import build_provider_for_role
                    from src.pipeline.image_pipeline import analyze_all_images

                    vision_provider = build_provider_for_role(self.config, "vision")
                    img_objs: list[ImageChunk] = []
                    for img in image_chunks:
                        img_objs.append(
                            ImageChunk(
                                chunk_id=str(img.get("chunk_id", "")),
                                doc_id=str(img.get("doc_id", doc_id)),
                                image_type=str(img.get("image_type", "")),
                                image_path=str(img.get("image_path", "")),
                                parent_chunk_id=img.get("parent_chunk_id"),
                                section_path=str(img.get("section_path", "")),
                                title=str(img.get("title", "")),
                                description=str(img.get("description", "")),
                                analysis=dict(img.get("analysis") or {}),
                                context=dict(img.get("context") or {}),
                                paragraph_index=int(img.get("paragraph_index", 0) or 0),
                                page_start=img.get("page_start"),
                            )
                        )

                    log.info("[Label s2] 开始图片 VL 预分析：%d 张（model=%s）", len(img_objs), vision_model)
                    analyze_all_images(
                        provider=vision_provider,
                        vision_model=vision_model,
                        image_chunks=img_objs,
                        skip_unknown=True,
                    )

                    # 回填到 dict 形式，供 Explorer/agents 使用与序列化
                    for i, obj in enumerate(img_objs):
                        image_chunks[i]["description"] = obj.description
                        image_chunks[i]["analysis"] = obj.analysis
                    log.info("[Label s2] 图片 VL 预分析完成：%d 张", len(img_objs))
                except Exception as e:
                    log.warning("[Label s2] 图片 VL 预分析失败，继续执行（I* 维度可能缺少 analysis）: %s", e)
        elif self.scenario == "s2" and image_chunks and not enable_vision_analysis:
            log.info("[Label s2] 已关闭图片 VL 预分析（设置 INDUSTRY_ENABLE_VISION_ANALYSIS=1 可开启）")

        # Explorer A ‖ Explorer B 并发
        explorer_a = self._factory.build("a")
        explorer_b = self._factory.build("b")

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="explorer"
        ) as pool:
            fut_a = pool.submit(
                explorer_a.run, doc_id,
                [c.to_row() for c in chunks],
                image_chunks,
                self.scenario,
                progress_cb,  # 仅 A 上报进度，避免 A/B 重复计数
            )
            fut_b = pool.submit(
                explorer_b.run, doc_id,
                [c.to_row() for c in chunks],
                image_chunks,
                self.scenario,
                None,
            )
            a_results = fut_a.result()
            b_results = fut_b.result()

        log.info("[Label] A/B 完成，分歧维度: %s",
                 [d for d in a_results if
                  d in b_results and a_results[d].verdict != b_results[d].verdict])

        # Critic 仲裁
        sample = [c.to_row() for c in chunks[:4]]
        final = self._critic.run(doc_id, a_results, b_results, sample)

        # Metrics
        elapsed = time.perf_counter() - t0
        ctx = MetricsContext(
            doc_path=path, chunks=chunks, elapsed_seconds=elapsed,
            input_format=path.suffix.lower(), parse_succeeded=bool(chunks),
        )
        for dim, res in compute_metrics(ctx).items():
            final[dim] = res
            if progress_cb:
                try:
                    progress_cb(dim, res.verdict)
                except Exception:
                    pass

        # 持久化 GT labels
        for dim, res in final.items():
            a_raw = a_results.get(dim)
            b_raw = b_results.get(dim)
            self.repo.upsert_label(
                label_id=f"{doc_id}__{dim}__label",
                doc_id=doc_id,
                dimension=dim,
                pipeline="label",
                final_verdict=res.verdict,
                score=res.score,
                confidence=res.confidence,
                explorer_a=a_raw.to_dict() if a_raw else None,
                explorer_b=b_raw.to_dict() if b_raw else None,
                findings=[f.to_dict() for f in res.findings],
                extra=res.extra,
                need_human_review=res.need_human_review,
                human_signoff=False,
            )

        log.info("[Label] 完成，耗时 %.1fs，%d 维度 dims=%s scenario=%s", elapsed, len(final), list(final.keys()), self.scenario)
        return LabelResult(
            doc_id=doc_id,
            doc_name=path.name,
            dimensions=final,
            elapsed_seconds=elapsed,
            scenario=self.scenario,
        )

    def _ingest(self, path: Path, doc_id: str):
        """解析文档，返回 (chunks, image_chunks_by_type)。

        image_chunks_by_type 格式：
          [{"chunk_id": ..., "image_path": ..., "image_type": ...}, ...]
        """
        cfg = self.config
        out_dir = Path(cfg["paths"]["data_dir"]) / "tmp" / doc_id
        out_dir.mkdir(parents=True, exist_ok=True)
        image_dir = Path(cfg["paths"]["images_dir"]) / doc_id

        suffix = path.suffix.lower()

        if suffix == ".doc":
            path = convert_doc_to_docx(path, out_dir,
                                       timeout=cfg["parse"]["doc_to_docx_timeout"])
            suffix = ".docx"

        if suffix in (".docx", ".docm"):
            blocks = parse_docx(path, image_out_dir=image_dir)
        elif suffix == ".pdf":
            from src.parse.scan_detector import is_scanned_pdf
            from src.parse.pdf_parser import parse_pdf
            from src.parse.docx_parser import DocxBlock, DocxBlockType
            if is_scanned_pdf(path):
                log.warning("扫描件 PDF，OCR 模式")
                blocks = []
            else:
                pdf_pages = parse_pdf(path, image_out_dir=image_dir)
                blocks = []
                for page in pdf_pages:
                    if page.text.strip():
                        blocks.append(DocxBlock(
                            block_type=DocxBlockType.PARAGRAPH, text=page.text,
                            style="Normal", paragraph_index=page.page_num,
                        ))
                    for ip in page.images:
                        blocks.append(DocxBlock(
                            block_type=DocxBlockType.IMAGE, text="",
                            style="Normal", paragraph_index=page.page_num,
                            image_path=str(ip),
                        ))
        else:
            log.error("不支持格式 %s，返回空", suffix)
            return [], []

        chunks = chunk_docx_blocks(
            blocks, doc_id=doc_id,
            max_tokens=cfg["chunk"]["max_tokens"],
            table_inline_rows=cfg["chunk"]["table_inline_rows"],
        )
        from src.pipeline.audit import assign_dimensions
        assign_dimensions(chunks)
        self.repo.upsert_chunks(chunks)

        # 为图片构造上下文：利用 chunk_docx_blocks 生成的 IMAGE chunk 及其邻近 TEXT/HEADING
        # 目的：用于更稳的图片分类（尤其是文件名无语义时）。
        def _build_image_context_map() -> dict[str, dict[str, Any]]:
            from src.chunk.models import ChunkType

            # 将 chunk 还原成顺序（chunk_docx_blocks 的 paragraph_index 基于原文序）
            ordered = sorted(chunks, key=lambda c: (c.paragraph_index or 0, c.chunk_id))

            last_heading: str = ""
            last_text: str = ""
            last_heading_title: str = ""
            last_section_path: str = ""
            image_meta: dict[str, dict[str, Any]] = {}

            # 先扫一遍，记录每张图的“前文”信息与自身章节信息
            for c in ordered:
                if c.chunk_type == ChunkType.HEADING:
                    last_heading = (c.content or "")[:120]
                    last_heading_title = c.title or ""
                    last_section_path = c.section_path or ""
                elif c.chunk_type == ChunkType.TEXT:
                    # 只取头部片段，避免上下文过长
                    txt = (c.content or "").strip().replace("\n", " ")
                    if txt:
                        last_text = txt[:240]
                elif c.chunk_type == ChunkType.IMAGE:
                    ip = (c.extra or {}).get("image_path")
                    if not ip:
                        continue
                    p = str(Path(str(ip)).resolve())
                    image_meta[p] = {
                        "section_path": c.section_path or last_section_path,
                        "title": c.title or last_heading_title,
                        "paragraph_index": c.paragraph_index or 0,
                        "page_start": c.page_start,
                        "prev_heading": last_heading,
                        "prev_text": last_text,
                        # next_* 之后再补
                        "next_heading": "",
                        "next_text": "",
                    }

            # 再扫一遍（反向）补“后文”信息
            next_heading: str = ""
            next_text: str = ""
            for c in reversed(ordered):
                if c.chunk_type == ChunkType.HEADING:
                    next_heading = (c.content or "")[:120]
                elif c.chunk_type == ChunkType.TEXT:
                    txt = (c.content or "").strip().replace("\n", " ")
                    if txt:
                        next_text = txt[:240]
                elif c.chunk_type == ChunkType.IMAGE:
                    ip = (c.extra or {}).get("image_path")
                    if not ip:
                        continue
                    p = str(Path(str(ip)).resolve())
                    if p in image_meta:
                        image_meta[p]["next_heading"] = next_heading
                        image_meta[p]["next_text"] = next_text

            return image_meta

        image_ctx_meta = _build_image_context_map() if self.scenario == "s2" else {}

        # 场景二：收集图片路径，自动分类
        image_chunks: list[dict] = []
        if self.scenario == "s2" and image_dir.exists():
            all_images = sorted(
                [p for p in image_dir.rglob("*")
                 if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp")],
                key=lambda p: p.name,
            )
            if all_images:
                from collections import Counter

                from src.agents.scene2.image_classifier import (
                    classify_images,
                    map_classifier_label_to_agent_image_type,
                )
                # 分类不调用大模型：仅用文件名+上下文关键词
                # （context_by_path 已包含 section/title/前后文本）

                # path → 上下文串（给 VL 分类用）
                context_by_path: dict[str, str] = {}
                for p in all_images:
                    key = str(p.resolve())
                    meta = image_ctx_meta.get(key) or {}
                    ctx_lines = [
                        f"section_path: {meta.get('section_path','')}",
                        f"title: {meta.get('title','')}",
                        f"prev_heading: {meta.get('prev_heading','')}",
                        f"prev_text: {meta.get('prev_text','')}",
                        f"next_heading: {meta.get('next_heading','')}",
                        f"next_text: {meta.get('next_text','')}",
                    ]
                    context_by_path[key] = "\n".join(ctx_lines).strip()

                classified = classify_images(
                    [str(p) for p in all_images],
                    context_by_path=context_by_path,
                    context_meta_by_path=image_ctx_meta,
                )
                sem_counts: Counter[str] = Counter()
                for img_type, paths in classified.items():
                    for img_path in paths:
                        semantic = map_classifier_label_to_agent_image_type(img_type)
                        sem_counts[semantic] += 1
                        meta = image_ctx_meta.get(str(Path(img_path).resolve())) or {}
                        image_chunks.append({
                            "chunk_id": f"{doc_id}__{semantic}__{Path(img_path).stem}",
                            "doc_id": doc_id,
                            "image_type": semantic,
                            "image_path": img_path,
                            "description": "",
                            "analysis": {"classifier_label": img_type},
                            # 补充上下文，供 debug / 二次分类 / 视觉预分析使用
                            "section_path": meta.get("section_path", ""),
                            "title": meta.get("title", ""),
                            "paragraph_index": meta.get("paragraph_index", 0),
                            "page_start": meta.get("page_start"),
                            "context": {
                                "prev_heading": meta.get("prev_heading", ""),
                                "prev_text": meta.get("prev_text", ""),
                                "next_heading": meta.get("next_heading", ""),
                                "next_text": meta.get("next_text", ""),
                            },
                        })
                log.info(
                    "[Label s2] 图片分类 raw=%s → agent image_type=%s",
                    {k: len(v) for k, v in classified.items()},
                    dict(sem_counts),
                )

        return chunks, image_chunks

    def close(self) -> None:
        self.repo.close()
