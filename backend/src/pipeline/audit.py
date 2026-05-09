"""审核流水线：单文档 → 解析 → 切块 → 入库 → 多维度 agent → metrics → 输出。"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.agents import (
    AgentResult,
    BaseAgent,
    C1StructureAgent,
    C2ContentAgent,
    C3LanguageAgent,
    C4ReferenceAgent,
    C5LogicAgent,
    E1StaffingAgent,
    E2EmergencyAgent,
    L2StandardsAgent,
)
from src.agents.base import AuditOpinion, AuditReport
from src.agents.audit_judgment import AuditJudgmentService
from src.agents.llm_audit_utils import build_section_toc
from src.agents.standards_seed import ensure_demo_standards
from src.chunk import Chunk, ChunkType, chunk_docx_blocks, chunk_parsed_blocks
from src.config import get_default_config
from src.llm import LLMProvider, build_provider
from src.metrics import MetricsContext, compute_metrics
from src.parse import convert_doc_to_docx, parse_docx
from src.store import Repository


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 标准库检索缓存
# ---------------------------------------------------------------------------


@dataclass
class StandardCache:
    """标准库检索缓存，按 dimension 分组。"""
    _cache: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    _user_id: str = ""

    def get(self, dimension: str) -> list[dict[str, Any]] | None:
        return self._cache.get(dimension)

    def set(self, dimension: str, snippets: list[dict[str, Any]]) -> None:
        self._cache[dimension] = snippets

    def prewarm(
        self,
        dimensions: list[str],
        repo: Repository | None,
        query: str,
        *,
        top_k: int = 5,
    ) -> None:
        """预热缓存：并行检索多个维度的标准条款。"""
        from src.agents.llm_audit_utils import retrieve_standard_snippets

        def _fetch(dim: str) -> tuple[str, list[dict[str, Any]]]:
            snippets = retrieve_standard_snippets(repo, dim, query, top_k=top_k)
            return dim, snippets

        with ThreadPoolExecutor(max_workers=len(dimensions)) as pool:
            futures = {pool.submit(_fetch, d): d for d in dimensions}
            for future in as_completed(futures):
                dim = futures[future]
                try:
                    _, snippets = future.result()
                    self.set(dim, snippets)
                except Exception as e:
                    log.warning("预热 %s 失败: %s", dim, e)


# ---------------------------------------------------------------------------
# 维度路由：哪些 chunk 喂给哪些维度
# ---------------------------------------------------------------------------

# E1 人员配备：相关关键词
E1_KEYWORDS = (
    "员工", "工程师", "巡护", "巡线", "区段长", "管道", "总长",
    "管辖", "里程", "天然气", "成品油", "输油", "HSE",
)


def is_relevant_for_e1(chunk: Chunk) -> bool:
    text = chunk.content or ""
    return any(kw in text for kw in E1_KEYWORDS)


def assign_dimensions(chunks: list[Chunk]) -> None:
    """把维度标签写到 chunk.dimensions（in-place）。

    注意：C1 和 C4 是文档级维度（要看全部 chunk 决定结构/引用），
    不需要预路由；这里只为细粒度维度（如 E1）做预路由。
    """
    for c in chunks:
        if is_relevant_for_e1(c):
            if "E1_staffing" not in c.dimensions:
                c.dimensions.append("E1_staffing")


# ---------------------------------------------------------------------------
# 结果类
# ---------------------------------------------------------------------------


@dataclass
class AuditResult:
    doc_id: str
    doc_name: str
    review_timestamp: str
    dimensions: dict[str, dict[str, Any]]
    audit_report: AuditReport | None = None  # 人工可读审核意见（LLM judgment 生成）
    overall_verdict: str = "uncertain"
    overall_score: int = 0
    need_human_review: bool = False
    elapsed_seconds: float = 0.0
    doc_summary: str = ""           # 文档内容摘要（前 ~200 字）
    converted_docx_path: str = ""   # .doc→.docx 转换路径，供批注器使用
    _chunks: list[Chunk] = field(default_factory=list)  # 内部缓存，供 navigation 使用

    def to_dict(self) -> dict[str, Any]:
        # S1 max = 8 core dims(C/E/L) x12 + 3 metrics(T1/T2/T3) x12 = 132
        max_score = 132
        raw_total = self.overall_score
        normalized_score = round(raw_total / max_score * 100) if max_score > 0 else 0
        chunks_rows = [c.to_row() for c in self._chunks]
        sections = build_section_toc(chunks_rows)
        total_sections = len(sections)
        return {
            "doc_id": self.doc_id,
            "doc_name": self.doc_name,
            "scenario": "s1",
            "review_timestamp": self.review_timestamp,
            "dimensions": self.dimensions,
            "audit_report": self.audit_report.to_dict() if self.audit_report else None,
            "overall_verdict": self.overall_verdict,
            "overall_score": normalized_score,
            "raw_score": raw_total,
            "max_score": max_score,
            "need_human_review": self.need_human_review,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "doc_summary": self.doc_summary,
            "converted_docx_path": self.converted_docx_path,
            "navigation": {
                "sections": sections,
                "total_sections": total_sections,
            },
        }


def derive_doc_id(path: Path) -> str:
    stem = path.stem
    return re.sub(r"[^A-Za-z0-9_-]+", "_", stem)[:80]


def compute_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# 顶层 pipeline
# ---------------------------------------------------------------------------


class AuditPipeline:
    """多维度审核 pipeline。

    维度分两类：
    1. **agents**：BaseAgent 子类。喂 chunks，输出 AgentResult。
    2. **metrics**：T1-T3，从运行上下文（耗时/格式）推导，不调 LLM。

    新增维度只需要：
    - 实现 BaseAgent 子类
    - 在 _build_agents() 里 register
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        provider: LLMProvider | None = None,
        repo: Repository | None = None,
        standard_cache: StandardCache | None = None,
    ) -> None:
        self.config = config or get_default_config()
        self.provider = provider or build_provider(self.config)
        db_path = self.config.get("paths", {}).get("db_path", ":memory:")
        self.repo = repo or Repository(db_path)
        self._standard_cache = standard_cache

        text_model = self.config.get("llm", {}).get("text_model", "Qwen3-2B")
        ensure_demo_standards(self.repo)
        self.agents: list[BaseAgent] = self._build_agents(text_model)
        self._last_converted_docx: str = ""  # .doc 转换后的临时 .docx 路径

    def _build_agents(self, text_model: str) -> list[BaseAgent]:
        llm_cfg = self.config.get("llm", {}) or {}
        explorer_a_temp = float(llm_cfg.get("explorer_a_temperature", 0.2))
        cache = self._standard_cache
        return [
            C1StructureAgent(self.provider, text_model),
            C4ReferenceAgent(self.provider, text_model),
            C2ContentAgent(self.provider, text_model, repo=self.repo, standard_cache=cache),
            C3LanguageAgent(self.provider, text_model, repo=self.repo, standard_cache=cache),
            E2EmergencyAgent(self.provider, text_model, repo=self.repo, standard_cache=cache),
            L2StandardsAgent(self.provider, text_model, repo=self.repo, standard_cache=cache),
            C5LogicAgent(
                self.provider,
                text_model,
                repo=self.repo,
                explorer_a_temperature=explorer_a_temp,
            ),
            E1StaffingAgent(self.provider, text_model),
        ]

    # ------------------------------------------------------------------
    def run(self, doc_path: str | Path, progress_cb=None) -> AuditResult:
        t0 = time.perf_counter()
        path = Path(doc_path).resolve()
        doc_id = derive_doc_id(path)
        file_hash = compute_file_hash(path)
        log.info("Auditing %s as doc_id=%s", path.name, doc_id)

        # 1) 解析 + 切块 + 入库
        parse_ok = True
        try:
            chunks = self._ingest(path, doc_id, file_hash)
        except Exception as e:
            log.error("Ingest failed for %s: %s", path.name, e)
            chunks = []
            parse_ok = False

        # 1.5) 预热标准库缓存（多个维度并行检索）
        if self._standard_cache is not None and chunks:
            doc_text = " ".join(c.content or "" for c in chunks[:20])
            self._standard_cache.prewarm(
                dimensions=["C2_content_completeness", "C3_language", "E2_emergency", "L2_standards"],
                repo=self.repo,
                query=doc_text[:600],
                top_k=5,
            )

        # 2) 并行跑所有 agent（LLM 调用是 I/O bound，ThreadPool 不受 GIL 限制）
        dim_results: dict[str, AgentResult] = {}
        if parse_ok and chunks:
            with ThreadPoolExecutor(max_workers=len(self.agents)) as pool:
                futures = {
                    pool.submit(self._run_agent, agent, chunks): agent
                    for agent in self.agents
                }
                for fut in as_completed(futures):
                    agent = futures[fut]
                    try:
                        res = fut.result()
                    except Exception as e:
                        log.exception("Agent %s 执行失败", agent.dimension)
                        res = AgentResult(
                            dimension=agent.dimension,
                            verdict="uncertain",
                            confidence=10,
                            details=f"agent 执行异常：{e}",
                            need_human_review=True,
                        )
                    dim_results[res.dimension] = res
                    if progress_cb:
                        try:
                            progress_cb(res.dimension, res.verdict)
                        except Exception:
                            pass

        # 3) 跑 metrics（T1-T3）
        elapsed = time.perf_counter() - t0
        ctx = MetricsContext(
            doc_path=path,
            chunks=chunks,
            elapsed_seconds=elapsed,
            input_format=path.suffix.lower(),
            parse_succeeded=parse_ok,
        )
        for dim, res in compute_metrics(ctx).items():
            dim_results[dim] = res
            if progress_cb:
                try:
                    progress_cb(dim, res.verdict)
                except Exception:
                    pass

        # 4) 持久化所有维度
        for res in dim_results.values():
            self._persist_label(doc_id, res)

        # 5) LLM judgment — 基于 label 结果生成人工可读审核意见
        audit_opinions = self._run_label_judgment(dim_results)

        # 6) 构建人工可读报告
        audit_report = self._build_audit_report(
            doc_id, path.name, dim_results, audit_opinions, elapsed,
        )

        # 7) 汇总
        overall_verdict, overall_score = self._aggregate(dim_results)

        doc_summary = self._extract_summary(chunks)

        return AuditResult(
            doc_id=doc_id,
            doc_name=path.name,
            review_timestamp=dt.datetime.now().isoformat(),
            dimensions={k: v.to_dict() for k, v in dim_results.items()},
            audit_report=audit_report,
            overall_verdict=overall_verdict,
            overall_score=overall_score,
            need_human_review=any(r.need_human_review for r in dim_results.values()),
            elapsed_seconds=elapsed,
            doc_summary=doc_summary,
            converted_docx_path=self._last_converted_docx,
            _chunks=chunks,
        )

    # ------------------------------------------------------------------
    def _ingest(self, path: Path, doc_id: str, file_hash: str) -> list[Chunk]:
        cfg = self.config
        cached = self.repo.get_document_cache(file_hash)
        if cached:
            cached_doc_id = cached.get("doc_id", "")
            cached_rows = self.repo.get_chunks_by_doc(cached_doc_id)
            if cached_doc_id and cached_rows:
                self._last_converted_docx = cached.get("converted_docx_path", "") or ""
                log.info(
                    "Cache hit for %s via doc_id=%s (file_hash=%s)",
                    path.name,
                    cached_doc_id,
                    file_hash[:12],
                )
                return [self._row_to_chunk(row) for row in cached_rows]

        out_dir = Path(cfg["paths"]["data_dir"]) / "tmp" / doc_id
        out_dir.mkdir(parents=True, exist_ok=True)

        parse_cfg = cfg.get("parse", {})
        use_mineru = parse_cfg.get("use_mineru", False)

        if use_mineru and path.suffix.lower() in {".pdf", ".pptx", ".xlsx"}:
            # 仅 PDF/PPTX/XLSX 直接走 MinerU（原生支持坐标）
            # DOCX/DOC 需要坐标时走 parse_docx_via_pdf（LibreOffice → PDF → MinerU）
            from src.parse.mineru_parser import parse_with_mineru
            log.info("Using MinerU parser for %s", path.name)
            cluster_ports = parse_cfg.get("mineru_cluster_ports")
            blocks, _, _ = parse_with_mineru(
                path,
                backend=parse_cfg.get("mineru_backend", "pipeline"),
                language=parse_cfg.get("mineru_language", "ch"),
                cluster_ports=cluster_ports,
            )
            chunks = chunk_parsed_blocks(
                blocks,
                doc_id=doc_id,
                max_tokens=cfg["chunk"]["max_tokens"],
            )
            assign_dimensions(chunks)
            self.repo.upsert_chunks(chunks)
            self.repo.upsert_document_cache(
                file_hash=file_hash,
                source_name=path.name,
                doc_id=doc_id,
                parsed_with="mineru_pdf",
                converted_docx_path="",
            )
            log.info("MinerU: stored %d chunks for %s", len(chunks), doc_id)
            return chunks

        # DOCX/DOC 需要坐标时，通过 LibreOffice 转 PDF 再用 MinerU 解析
        if use_mineru and path.suffix.lower() in (".docx", ".docm", ".doc"):
            from src.parse.mineru_parser import parse_docx_via_pdf
            log.info("DOCX/DOC with coords: LibreOffice → MinerU for %s", path.name)
            cluster_ports = parse_cfg.get("mineru_cluster_ports")
            try:
                blocks, _, _ = parse_docx_via_pdf(
                    path,
                    out_dir=out_dir,
                    backend=parse_cfg.get("mineru_backend", "pipeline"),
                    language=parse_cfg.get("mineru_language", "ch"),
                    cluster_ports=cluster_ports,
                )
                chunks = chunk_parsed_blocks(
                    blocks,
                    doc_id=doc_id,
                    max_tokens=cfg["chunk"]["max_tokens"],
                )
                assign_dimensions(chunks)
                self.repo.upsert_chunks(chunks)
                self.repo.upsert_document_cache(
                    file_hash=file_hash,
                    source_name=path.name,
                    doc_id=doc_id,
                    parsed_with="mineru_docx_pdf",
                    converted_docx_path="",
                )
                log.info("DOCX_via_PDF: stored %d chunks for %s", len(chunks), doc_id)
                return chunks
            except Exception as e:
                # 环境缺少 LibreOffice/soffice 时，不应直接让 s1 秒失败。
                # 回退到原生 DOCX 解析继续审核（无坐标增强，但可产出完整审核结果）。
                log.warning(
                    "DOCX_via_PDF 失败，回退原生解析（无坐标增强）: %s",
                    e,
                )

        if path.suffix.lower() == ".doc":
            converted = convert_doc_to_docx(
                path, out_dir, timeout=cfg["parse"]["doc_to_docx_timeout"]
            )
            self._last_converted_docx = str(converted)
            blocks_path = converted
        else:
            self._last_converted_docx = ""
            blocks_path = path

        image_dir = Path(cfg["paths"]["images_dir"]) / doc_id

        if blocks_path.suffix.lower() in (".docx", ".docm"):
            blocks = parse_docx(blocks_path, image_out_dir=image_dir)
        elif blocks_path.suffix.lower() == ".pdf":
            # PDF 路径：先检测是否为扫描件
            from src.parse.scan_detector import is_scanned_pdf
            from src.parse.pdf_parser import parse_pdf, PdfPage

            if is_scanned_pdf(blocks_path):
                log.warning("扫描件 PDF，尝试 OCR（需安装 PaddleOCR）")
                try:
                    from src.parse.scan_detector import ocr_pdf_to_text
                    text = ocr_pdf_to_text(blocks_path)
                    # OCR 结果转成伪 block 列表
                    from src.parse.docx_parser import DocxBlock, DocxBlockType
                    blocks = [DocxBlock(
                        block_type=DocxBlockType.TEXT,
                        text=text,
                        style_name="Normal",
                        paragraph_index=0,
                    )]
                except Exception as e:
                    log.error("OCR 失败: %s", e)
                    blocks = []
            else:
                # 可编辑 PDF：提取文字 + 图片
                pdf_pages = parse_pdf(blocks_path, image_out_dir=image_dir)
                from src.parse.docx_parser import DocxBlock, DocxBlockType
                blocks = []
                for page in pdf_pages:
                    if page.text.strip():
                        blocks.append(DocxBlock(
                            block_type=DocxBlockType.TEXT,
                            text=page.text,
                            style_name="Normal",
                            paragraph_index=page.page_num,
                        ))
                    for img_path in page.images:
                        blocks.append(DocxBlock(
                            block_type=DocxBlockType.IMAGE,
                            text="",
                            style_name="Normal",
                            paragraph_index=page.page_num,
                            image_path=str(img_path),
                        ))
        else:
            raise NotImplementedError(f"不支持的格式: {blocks_path.suffix}")

        chunks = chunk_docx_blocks(
            blocks,
            doc_id=doc_id,
            max_tokens=cfg["chunk"]["max_tokens"],
            table_inline_rows=cfg["chunk"]["table_inline_rows"],
        )
        assign_dimensions(chunks)
        self.repo.upsert_chunks(chunks)
        parsed_with = "docx" if blocks_path.suffix.lower() in (".docx", ".docm") else "pdf"
        self.repo.upsert_document_cache(
            file_hash=file_hash,
            source_name=path.name,
            doc_id=doc_id,
            parsed_with=parsed_with,
            converted_docx_path=self._last_converted_docx,
        )
        log.info("Stored %d chunks for %s", len(chunks), doc_id)
        return chunks

    @staticmethod
    def _row_to_chunk(row: dict[str, Any]) -> Chunk:
        chunk_type = row.get("chunk_type", ChunkType.TEXT.value)
        chunk_type_enum = ChunkType(chunk_type)

        bbox = row.get("bbox")
        if isinstance(bbox, str):
            try:
                import json
                bbox = json.loads(bbox)
            except Exception:
                bbox = None

        return Chunk(
            chunk_id=row.get("chunk_id", ""),
            doc_id=row.get("doc_id", ""),
            chunk_type=chunk_type_enum,
            section_path=row.get("section_path", "") or "",
            title=row.get("title", "") or "",
            content=row.get("content", "") or "",
            paragraph_index=row.get("paragraph_index") or 0,
            anchor_text=row.get("anchor_text", "") or "",
            page_start=row.get("page_start"),
            page_end=row.get("page_end"),
            bbox=bbox,
            dimensions=list(row.get("dimensions") or []),
            cross_refs=list(row.get("cross_refs") or []),
            word_count=row.get("word_count") or 0,
            parent_id=row.get("parent_id"),
            extra=dict(row.get("extra") or {}),
        )

    # ------------------------------------------------------------------
    def _run_agent(self, agent: BaseAgent, chunks: list[Chunk]) -> AgentResult:
        """根据 agent 的维度路由相关 chunks。"""
        dim = agent.dimension

        # E1 用预路由的 dimensions 字段
        if dim == "E1_staffing":
            relevant = [c.to_row() for c in chunks if dim in c.dimensions]
            if not relevant:
                return AgentResult(
                    dimension=dim,
                    verdict="uncertain",
                    confidence=20,
                    details="未在文档中找到与人员配备相关的段落。",
                    need_human_review=True,
                )
            return agent.run(relevant)

        rows = [c.to_row() for c in chunks]
        return agent.run(rows)

    # ------------------------------------------------------------------
    @staticmethod
    def _extract_summary(chunks: list[Chunk]) -> str:
        """从前几个 chunk 拼接不超过 200 字的文档内容摘要（不调 LLM）。"""
        parts: list[str] = []
        total = 0
        for chunk in chunks[:8]:
            text = (chunk.content or "").strip()
            if not text:
                continue
            remaining = 200 - total
            if remaining <= 0:
                break
            parts.append(text[:remaining])
            total += len(text)
        summary = "".join(parts)[:200]
        return summary.replace("\n", " ").strip()

    # ------------------------------------------------------------------
    def _persist_label(self, doc_id: str, result: AgentResult) -> None:
        self.repo.upsert_label(
            label_id=f"{doc_id}__{result.dimension}__audit",
            doc_id=doc_id,
            dimension=result.dimension,
            pipeline="audit",
            final_verdict=result.verdict,
            score=result.score,
            confidence=result.confidence,
            findings=[f.to_dict() for f in result.findings],
            extra=result.extra,
            need_human_review=result.need_human_review,
            human_signoff=False,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _aggregate(dim_results: dict[str, AgentResult]) -> tuple[str, int]:
        """汇总 overall verdict 和总分。

        策略：
        - 任一维度 fail → overall fail
        - 任一维度 uncertain → overall uncertain（除非全是 metrics 维度的 fail）
        - 全部 pass → overall pass
        - 其余 → partial
        总分 = 各维度 score 之和（None 视为 0）
        """
        verdicts = [r.verdict for r in dim_results.values()]
        scores = [r.score or 0 for r in dim_results.values()]
        total = sum(scores)

        if not verdicts:
            return "uncertain", 0
        if "fail" in verdicts:
            return "fail", total
        if all(v == "pass" for v in verdicts):
            return "pass", total
        if "uncertain" in verdicts:
            return "uncertain", total
        return "partial", total

    # ------------------------------------------------------------------
    def _run_label_judgment(
        self, dim_results: dict[str, AgentResult]
    ) -> dict[str, list[AuditOpinion]]:
        """对所有维度的 label 结果做 LLM judgment，生成人工可读意见。"""
        judgment_model = self.config.get("llm", {}).get(
            "judgment_model",
            self.config.get("llm", {}).get("text_model", "deepseek-v3.2"),
        )
        service = AuditJudgmentService(self.provider, judgment_model)
        return service.run(dim_results)

    def _build_audit_report(
        self,
        doc_id: str,
        doc_name: str,
        dim_results: dict[str, AgentResult],
        audit_opinions: dict[str, list[AuditOpinion]],
        elapsed: float,
    ) -> AuditReport:
        """从 dim_results 和 audit_opinions 构建完整人工可读报告。"""
        all_opinions: list[AuditOpinion] = []
        for opinions in audit_opinions.values():
            all_opinions.extend(opinions)

        # 高危问题：severity=high 且 verdict!=pass
        critical_issues = [
            o.opinion for o in all_opinions
            if o.severity == "high" and o.verdict != "pass"
        ]

        # 总体建议：收集所有 suggestions，去重限10条
        seen: set[str] = set()
        recommendations: list[str] = []
        for o in all_opinions:
            for s in o.suggestions:
                if s and s not in seen:
                    seen.add(s)
                    recommendations.append(s)
                    if len(recommendations) >= 10:
                        break
            if len(recommendations) >= 10:
                break

        # 总体意见：综合各维度问题，生成一句话总结
        overall_opinion = self._synthesize_overall_opinion(audit_opinions)

        overall_verdict, overall_score = self._aggregate(dim_results)

        return AuditReport(
            doc_id=doc_id,
            doc_name=doc_name,
            overall_opinion=overall_opinion,
            overall_verdict=overall_verdict,
            overall_score=overall_score,
            per_dimension=audit_opinions,
            critical_issues=critical_issues,
            recommendations=recommendations,
            need_human_review=any(r.need_human_review for r in dim_results.values()),
            elapsed_seconds=elapsed,
        )

    @staticmethod
    def _synthesize_overall_opinion(
        audit_opinions: dict[str, list[AuditOpinion]]
    ) -> str:
        """综合各维度意见，生成一句话总体评价。"""
        fail_count = sum(
            1 for ops in audit_opinions.values()
            for o in ops if o.verdict == "fail"
        )
        partial_count = sum(
            1 for ops in audit_opinions.values()
            for o in ops if o.verdict == "partial"
        )
        total = sum(len(ops) for ops in audit_opinions.values())

        if fail_count > 0:
            return f"文档存在 {fail_count} 项严重问题，需要重点整改后方可使用。"
        if partial_count > 0:
            return f"文档存在 {partial_count} 项待改进之处，建议按建议优化后可投入使用。"
        if total > 0:
            return "文档基本符合要求，仅有个别细节需注意。"
        return "文档审核完成，未发现明显问题。"

    def close(self) -> None:
        self.repo.close()


def audit_document(
    doc_path: str | Path,
    config: dict[str, Any] | None = None,
) -> AuditResult:
    pipe = AuditPipeline(config=config)
    try:
        return pipe.run(doc_path)
    finally:
        pipe.close()


def audit_batch(
    doc_paths: list[str | Path],
    config: dict[str, Any] | None = None,
    *,
    max_workers: int = 3,
    on_done: "Callable[[str, AuditResult | Exception], None] | None" = None,
) -> dict[str, AuditResult | Exception]:
    """批量审核多个文档。

    并发策略：
    - max_workers 个文档同时走 ingest（默认3，匹配 MinerU Semaphore）
    - 每个文档内部 11 个 Agent 仍并发跑
    - MinerU Semaphore(3) 自动排队，超出上限的 ingest 等待而非报错
    - on_done 回调：每完成一个文档立即触发（用于实时进度反馈）

    返回 {doc_path_str: AuditResult | Exception}
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from typing import Callable

    cfg = config or get_default_config()
    results: dict[str, AuditResult | Exception] = {}

    def _run_one(path: Path) -> tuple[str, AuditResult | Exception]:
        pipe = AuditPipeline(config=cfg)
        try:
            result = pipe.run(path)
            return str(path), result
        except Exception as e:
            log.exception("批量审核失败: %s", path.name)
            return str(path), e
        finally:
            pipe.close()

    paths = [Path(p) for p in doc_paths]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_run_one, p): p for p in paths}
        for fut in as_completed(futures):
            key, outcome = fut.result()
            results[key] = outcome
            if on_done:
                on_done(key, outcome)
            name = Path(key).name
            status = "✓" if isinstance(outcome, AuditResult) else "✗"
            log.info("批量进度 %s %s  (%d/%d)", status, name, len(results), len(paths))

    return results
