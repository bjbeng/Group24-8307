"""MinerU 文档解析服务。

架构：进程级单例 MinerUService
- 本地 API 只启动一次，整个 backend 生命周期内复用
- Semaphore(3) 匹配服务器并发限制，超出自动排队
- 线程安全：pipeline 和任意 Agent 均可并发调用
- parse_with_mineru() 是向后兼容的便捷入口

支持格式：PDF / DOCX / DOC（MinerU 3.x）
坐标系：bbox = [x0, y0, x1, y1]，0-1000 归一化
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

# MinerU 本地 API 的最大并发任务数（与服务器配置一致）
_MINERU_MAX_CONCURRENT = 3

# 默认实例端口（单机模式）
_DEFAULT_PORT = 8000


# ---------------------------------------------------------------------------
# 多实例负载均衡器
# ---------------------------------------------------------------------------


class MinerUCluster:
    """MinerU 多实例集群，按 round-robin 分配请求。

    每个实例有独立 Semaphore(3)，实现 N×3 并发解析能力。
    线程安全，支持动态添加/移除实例。
    """

    def __init__(self, ports: list[int] | None = None) -> None:
        self._instances: list[_MinerUInstance] = []
        self._idx = 0
        self._lock = threading.Lock()
        if ports:
            for port in ports:
                self.add_instance(port)

    def add_instance(self, port: int) -> None:
        """动态添加一个 MinerU 实例。"""
        inst = _MinerUInstance(port)
        with self._lock:
            self._instances.append(inst)
        log.info("MinerU cluster: added instance at port %d", port)

    @property
    def instance_count(self) -> int:
        with self._lock:
            return len(self._instances)

    def _acquire(self) -> tuple[str, threading.Semaphore]:
        """返回 (base_url, semaphore) 供调用方持有。"""
        with self._lock:
            if not self._instances:
                raise RuntimeError("MinerU cluster has no instances")
            inst = self._instances[self._idx % len(self._instances)]
            self._idx += 1
        return inst.base_url, inst.semaphore

    def parse(
        self,
        file_path: str | Path,
        *,
        backend: str = "pipeline",
        language: str = "ch",
        table_enable: bool = True,
        start_page: int = 0,
        end_page: int | None = None,
    ) -> tuple[list[ParsedBlock], str | None, list[dict]]:
        """用 round-robin 从集群中选取实例执行解析。"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")

        base_url, semaphore = self._acquire()
        page_info = f" pages={start_page}-{end_page if end_page is not None else 'end'}"
        log.info("MinerU cluster parse: %s via %s (backend=%s%s)", path.name, base_url, backend, page_info)

        with semaphore:
            return _do_parse_remote(path, base_url, backend, language, table_enable, start_page, end_page)

    def parse_parallel(
        self,
        file_path: str | Path,
        *,
        n_workers: int = 4,
        backend: str = "pipeline",
        language: str = "ch",
        table_enable: bool = True,
    ) -> tuple[list[ParsedBlock], str | None, list[dict]]:
        """大文档分页并行解析，集群内 round-robin 分配各 page range。"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")

        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                total_pages = len(pdf.pages)
        except Exception:
            total_pages = 9999

        step = (total_pages + n_workers - 1) // n_workers
        ranges: list[tuple[int, int | None]] = []
        for i in range(n_workers):
            lo = i * step
            hi = min((i + 1) * step - 1, total_pages - 1)
            if lo >= total_pages:
                break
            ranges.append((lo, hi))

        if len(ranges) == 1:
            return self.parse(path, backend=backend, language=language, table_enable=table_enable,
                              start_page=ranges[0][0], end_page=ranges[0][1])

        log.info("MinerU cluster parse_parallel: %s 分为 %d 段 %s", path.name, len(ranges),
                 ", ".join(f"[{l}-{h}]" for l, h in ranges))

        def _parse_range(args: tuple[int, int | None]) -> tuple[list[ParsedBlock], str | None, list[dict]]:
            lo, hi = args
            return self.parse(path, backend=backend, language=language, table_enable=table_enable,
                              start_page=lo, end_page=hi)

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(ranges)) as pool:
            futures = [pool.submit(_parse_range, r) for r in ranges]
            parts = [f.result() for f in concurrent.futures.as_completed(futures)]

        parts.sort(key=lambda p: min(b.page_idx for b in p[0]) if p[0] else 0)
        merged_blocks: list[ParsedBlock] = []
        doc_summaries: list[str | None] = []
        merged_toc: list[dict] = []
        for part_blocks, part_summary, part_toc in parts:
            merged_blocks.extend(part_blocks)
            if part_summary:
                doc_summaries.append(part_summary)
            merged_toc.extend(part_toc)

        doc_summary = next((s for s in doc_summaries if s), None)
        seen_toc: set[tuple[int, str]] = set()
        unique_toc: list[dict] = []
        for entry in sorted(merged_toc, key=lambda x: x["page_idx"]):
            key = (entry["level"], entry["heading"])
            if key not in seen_toc:
                seen_toc.add(key)
                unique_toc.append(entry)

        log.info("MinerU cluster parse_parallel: 合并为 %d 个块", len(merged_blocks))
        return merged_blocks, doc_summary, unique_toc


class _MinerUInstance:
    """单个 MinerU 实例（host:port + 独立并发限制）。"""
    __slots__ = ("port", "base_url", "semaphore")

    def __init__(self, port: int) -> None:
        self.port = port
        self.base_url = f"http://127.0.0.1:{port}"
        self.semaphore = threading.Semaphore(_MINERU_MAX_CONCURRENT)


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class ParsedBlock:
    """MinerU 解析出的单个内容块，携带精确坐标。"""

    block_type: str             # "heading" / "text" / "table" / "image" / "other"
    text: str                   # 文本内容（table 为空，用 table_html）
    page_idx: int               # 页码，0-based
    bbox: list[float]           # [x0, y0, x1, y1]，0-1000 归一化坐标
    heading_level: int | None = None   # 1/2/3，仅 block_type=="heading" 时有值
    table_html: str | None = None      # 仅 block_type=="table"
    image_path: str | None = None      # 仅 block_type=="image"
    extra: dict[str, Any] = field(default_factory=dict)
    # === 新增字段 ===
    doc_summary: str | None = None           # 文档级摘要（来自第一段文字）
    table_of_contents: list[dict] | None = None  # [{"level":1,"heading":"...","page_idx":0},...]

    @property
    def page_number(self) -> int:
        """1-based 页码，与旧 DocxBlock 接口兼容。"""
        return self.page_idx + 1


# ---------------------------------------------------------------------------
# content_list → ParsedBlock 转换（内部工具）
# ---------------------------------------------------------------------------

_SKIP_TYPES = {"header", "footer", "page_number", "page_footnote", "aside_text"}

import logging as _logging
_logger = _logging.getLogger(__name__)


def _content_list_to_blocks(content_list: list[dict[str, Any]]) -> tuple[list[ParsedBlock], str | None, list[dict]]:
    """转换 content_list 为 (blocks, doc_summary, toc)。

    - doc_summary：第一个够长的 text 块前300字
    - toc：所有 heading 块，按 page_idx 排序
    """
    blocks: list[ParsedBlock] = []
    doc_summary: str | None = None
    toc: list[dict] = []

    for item in content_list:
        item_type = item.get("type", "text")
        page_idx = item.get("page_idx", 0)
        bbox = item.get("bbox") or [0, 0, 0, 0]

        if item_type in _SKIP_TYPES:
            continue

        if item_type == "table":
            blocks.append(ParsedBlock(
                block_type="table",
                text="",
                page_idx=page_idx,
                bbox=bbox,
                table_html=item.get("table_body", ""),
            ))
            continue

        if item_type == "image":
            blocks.append(ParsedBlock(
                block_type="image",
                text=item.get("image_caption", ""),
                page_idx=page_idx,
                bbox=bbox,
                image_path=item.get("img_path"),
            ))
            continue

        text = item.get("text", "").strip()
        if not text:
            continue

        text_level = item.get("text_level")
        if text_level and text_level >= 1:
            blocks.append(ParsedBlock(
                block_type="heading",
                text=text,
                page_idx=page_idx,
                bbox=bbox,
                heading_level=int(text_level),
            ))
            toc.append({"level": int(text_level), "heading": text, "page_idx": page_idx})
        else:
            blocks.append(ParsedBlock(
                block_type="text",
                text=text,
                page_idx=page_idx,
                bbox=bbox,
            ))
            # 收集 doc_summary（第一个够长的 text）
            if not doc_summary and len(text) > 50:
                doc_summary = text[:300]

    # TOC 按 page_idx 排序
    toc.sort(key=lambda x: x["page_idx"])

    # Debug: log heading page_idx values to diagnose MinerU office backend bug
    heading_items = [(i, item.get("text", "")[:40], item.get("page_idx")) for i, item in enumerate(content_list) if item.get("text_level", 0) >= 1]
    if heading_items:
        _logger.debug(
            "Heading page_idx in content_list (%d headings): %s",
            len(heading_items),
            [(text[:20], pidx) for _, text, pidx in heading_items],
        )

    return blocks, doc_summary, toc


# ---------------------------------------------------------------------------
# MinerUService — 进程级单例
# ---------------------------------------------------------------------------


class MinerUService:
    """MinerU 本地 API 的进程级单例服务。

    生命周期：
    - 第一次 parse() 调用时惰性启动（延迟初始化）
    - 进程退出时自动关闭（__del__）
    - 也可手动调用 stop() / start()

    并发：
    - Semaphore(3) 限制同时解析数量，与 MinerU 服务器配置一致
    - 超出上限的请求自动排队等待，不会出错
    - 线程安全，多 Agent 可并发调用
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._semaphore = threading.Semaphore(_MINERU_MAX_CONCURRENT)
        self._server: Any = None
        self._base_url: str | None = None
        self._started = False

    # ── 生命周期 ──────────────────────────────────────────────────────────

    def start(self) -> None:
        """启动 MinerU 本地 API（幂等，重复调用无副作用）。"""
        if self._started:
            return
        with self._lock:
            if self._started:
                return
            self._do_start()
            self._started = True

    def _do_start(self) -> None:
        from mineru.cli import api_client

        self._server = api_client.LocalAPIServer()
        self._base_url = self._server.start()
        log.info("MinerU service started: %s", self._base_url)

        async def _wait() -> None:
            async with httpx.AsyncClient(
                timeout=api_client.build_http_timeout(),
                follow_redirects=True,
            ) as client:
                await api_client.wait_for_local_api_ready(client, self._server)

        asyncio.run(_wait())
        log.info("MinerU service ready")

    def stop(self) -> None:
        """关闭 MinerU 本地 API。"""
        with self._lock:
            if self._server and self._started:
                try:
                    self._server.stop()
                except Exception:
                    pass
                self._started = False
                log.info("MinerU service stopped")

    def __del__(self) -> None:
        self.stop()

    # ── 解析入口 ──────────────────────────────────────────────────────────

    def parse(
        self,
        file_path: str | Path,
        *,
        backend: str = "pipeline",
        language: str = "ch",
        table_enable: bool = True,
        start_page: int = 0,
        end_page: int | None = None,
    ) -> tuple[list[ParsedBlock], str | None, list[dict]]:
        """解析文档，返回 (blocks, doc_summary, toc)。

        start_page / end_page：物理页范围（0-based, inclusive）。
        省略 end_page 则解析到末尾。
        线程安全，并发超过 3 时自动排队等待。
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")

        self.start()  # 惰性启动，已启动则 no-op

        page_info = f" pages={start_page}-{end_page if end_page is not None else 'end'}"
        log.info("MinerU parse: %s (backend=%s%s)", path.name, backend, page_info)

        with self._semaphore:  # 排队：超过 3 个并发时阻塞等待
            return self._do_parse(
                path,
                backend=backend,
                language=language,
                table_enable=table_enable,
                start_page=start_page,
                end_page=end_page,
            )

    def _do_parse(
        self,
        path: Path,
        *,
        backend: str,
        language: str,
        table_enable: bool,
        start_page: int = 0,
        end_page: int | None = None,
    ) -> tuple[list[ParsedBlock], str | None, list[dict]]:
        """实际执行一次解析任务（持有 semaphore 时调用）。"""
        return _do_parse_remote(
            path,
            self._base_url,
            backend,
            language,
            table_enable,
            start_page,
            end_page,
        )

    def parse_parallel(
        self,
        file_path: str | Path,
        *,
        n_workers: int = 4,
        backend: str = "pipeline",
        language: str = "ch",
        table_enable: bool = True,
    ) -> tuple[list[ParsedBlock], str | None, list[dict]]:
        """大文档分页并行解析。

        将文档按页数均分为 n_workers 段，每段并发调 parse()，
        结果按 page_idx 合并后返回 (blocks, doc_summary, toc)。

        例如：500页 PDF，n_workers=4 → 4段并行：
          [0-124], [125-249], [250-374], [375-499]

        Semaphore(3) 自动限流：n_workers > 3 时第4个调用排队等待。
        页码统一成全局索引（0-based）。
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")

        # 先快速取总页数（用 pdfplumber）
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                total_pages = len(pdf.pages)
        except Exception:
            total_pages = 9999

        step = (total_pages + n_workers - 1) // n_workers
        ranges: list[tuple[int, int | None]] = []
        for i in range(n_workers):
            lo = i * step
            hi = min((i + 1) * step - 1, total_pages - 1)
            if lo >= total_pages:
                break
            ranges.append((lo, hi))

        if len(ranges) == 1:
            return self.parse(
                path, backend=backend, language=language,
                table_enable=table_enable,
                start_page=ranges[0][0], end_page=ranges[0][1],
            )

        log.info(
            "MinerU parse_parallel: %s 分为 %d 段 %s",
            path.name, len(ranges),
            ", ".join(f"[{l}-{h}]" for l, h in ranges),
        )

        def _parse_range(args: tuple[int, int | None]) -> tuple[list[ParsedBlock], str | None, list[dict]]:
            lo, hi = args
            return self.parse(
                path,
                backend=backend,
                language=language,
                table_enable=table_enable,
                start_page=lo,
                end_page=hi,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(ranges)) as pool:
            futures = [pool.submit(_parse_range, r) for r in ranges]
            parts = [f.result() for f in concurrent.futures.as_completed(futures)]

        # 按 start_page 排序后合并
        parts.sort(key=lambda p: min(b.page_idx for b in p[0]) if p[0] else 0)
        merged_blocks: list[ParsedBlock] = []
        doc_summaries: list[str | None] = []
        merged_toc: list[dict] = []
        for part_blocks, part_summary, part_toc in parts:
            merged_blocks.extend(part_blocks)
            if part_summary:
                doc_summaries.append(part_summary)
            merged_toc.extend(part_toc)

        # doc_summary 取第一个有效的
        doc_summary = next((s for s in doc_summaries if s), None)
        # TOC 按 page_idx 排序并去重（按 (level, heading) 去重）
        seen_toc: set[tuple[int, str]] = set()
        unique_toc: list[dict] = []
        for entry in sorted(merged_toc, key=lambda x: x["page_idx"]):
            key = (entry["level"], entry["heading"])
            if key not in seen_toc:
                seen_toc.add(key)
                unique_toc.append(entry)

        log.info("MinerU parse_parallel: 合并为 %d 个块", len(merged_blocks))
        return merged_blocks, doc_summary, unique_toc

    # ---------------------------------------------------------------------------
# 远程解析（给 MinerUCluster 用，从已有 _do_parse 抽出）
# ---------------------------------------------------------------------------


def _do_parse_remote(
    path: Path,
    base_url: str,
    backend: str,
    language: str,
    table_enable: bool,
    start_page: int = 0,
    end_page: int | None = None,
) -> tuple[list[ParsedBlock], str | None, list[dict]]:
    """实际执行一次解析任务，发送给指定 base_url 的 MinerU 服务。"""
    from mineru.cli import api_client

    async def _run() -> list[dict[str, Any]]:
        form_data = api_client.build_parse_request_form_data(
            lang_list=[language],
            backend=backend,
            parse_method="auto",
            formula_enable=False,
            table_enable=table_enable,
            server_url=None,
            start_page_id=start_page,
            end_page_id=end_page,
            return_md=False,
            return_middle_json=False,
            return_model_output=False,
            return_content_list=True,
            return_images=False,
            response_format_zip=True,
            return_original_file=False,
        )
        upload_assets = [
            api_client.UploadAsset(path=path, upload_name=path.name)
        ]

        async with httpx.AsyncClient(
            timeout=api_client.build_http_timeout(),
            follow_redirects=True,
        ) as client:
            submit = await api_client.submit_parse_task(
                base_url=base_url,
                upload_assets=upload_assets,
                form_data=form_data,
            )
            log.debug("MinerU task_id=%s via %s", submit.task_id, base_url)
            await api_client.wait_for_task_result(
                client=client,
                submit_response=submit,
                task_label=path.name,
            )
            result_zip_path = await api_client.download_result_zip(
                client=client,
                submit_response=submit,
                task_label=path.name,
            )

        content_list: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory() as tmp:
            api_client.safe_extract_zip(result_zip_path, Path(tmp))
            result_zip_path.unlink(missing_ok=True)
            for json_file in Path(tmp).rglob("*_content_list.json"):
                with open(json_file, encoding="utf-8") as f:
                    content_list = json.load(f)
                log.debug("content_list: %d items from %s", len(content_list), json_file.name)
                break

        if not content_list:
            log.warning("content_list.json 为空: %s", path.name)
        return content_list

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(asyncio.run, _run())
            content_list = fut.result()
    else:
        content_list = asyncio.run(_run())

    blocks, doc_summary, toc = _content_list_to_blocks(content_list)
    if blocks:
        blocks[0] = ParsedBlock(
            block_type=blocks[0].block_type,
            text=blocks[0].text,
            page_idx=blocks[0].page_idx,
            bbox=blocks[0].bbox,
            heading_level=blocks[0].heading_level,
            table_html=blocks[0].table_html,
            image_path=blocks[0].image_path,
            extra=blocks[0].extra,
            doc_summary=doc_summary,
            table_of_contents=toc,
        )
    return blocks, doc_summary, toc


# ---------------------------------------------------------------------------
# 进程级单例
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 进程级单例（支持单机 MinerUService 和多机 MinerUCluster）
# ---------------------------------------------------------------------------

_cluster_lock = threading.Lock()
_cluster: MinerUCluster | None = None


def get_mineru_cluster(ports: list[int] | None = None) -> MinerUCluster:
    """获取进程级 MinerUCluster 多实例集群。

    ports: 实例端口列表，如 [8001, 8002, 8003]
           空列表则只启动本地单机实例
    """
    global _cluster
    if _cluster is not None:
        return _cluster
    with _cluster_lock:
        if _cluster is None:
            _cluster = MinerUCluster(ports) if ports else MinerUCluster([_DEFAULT_PORT])
    return _cluster


_service_lock = threading.Lock()
_service: MinerUService | None = None


def get_mineru_service() -> MinerUService:
    """获取进程级 MinerUService 单例（单机模式，调用本地 MinerU 实例）。

    注意：若要使用多实例集群，请用 get_mineru_cluster()。
    """
    global _service
    if _service is not None:
        return _service
    with _service_lock:
        if _service is None:
            _service = MinerUService()
    return _service


# ---------------------------------------------------------------------------
# 向后兼容入口
# ---------------------------------------------------------------------------


def parse_with_mineru(
    file_path: str | Path,
    *,
    backend: str = "pipeline",
    language: str = "ch",
    table_enable: bool = True,
    start_page: int = 0,
    end_page: int | None = None,
    cluster_ports: list[int] | None = None,
) -> tuple[list[ParsedBlock], str | None, list[dict]]:
    """解析文档，返回 (blocks, doc_summary, toc)。

    cluster_ports: 若指定，则使用 MinerUCluster 多实例模式（round-robin）
                   如 [8001, 8002, 8003] 实现 3×3=9 并发解析。
                   若为 None，则使用单机 MinerUService。
    """
    if cluster_ports:
        cluster = get_mineru_cluster(cluster_ports)
        return cluster.parse(
            file_path,
            backend=backend,
            language=language,
            table_enable=table_enable,
            start_page=start_page,
            end_page=end_page,
        )
    return get_mineru_service().parse(
        file_path,
        backend=backend,
        language=language,
        table_enable=table_enable,
        start_page=start_page,
        end_page=end_page,
    )


def parse_docx_via_pdf(
    docx_path: str | Path,
    *,
    out_dir: str | Path | None = None,
    backend: str = "pipeline",
    language: str = "ch",
    table_enable: bool = True,
    cluster_ports: list[int] | None = None,
    timeout: float = 120.0,
) -> tuple[list[ParsedBlock], str | None, list[dict]]:
    """DOCX → LibreOffice PDF → MinerU 解析，返回带完整坐标的 blocks。

    用于：DOCX 本身无坐标，通过中间 PDF 获取 bbox/page_number。
    流程：DOCX --[LibreOffice]--> PDF --[MinerU]--> blocks(bbox/page_idx 完整)

    注意：PDF 坐标基于 LibreOffice 渲染结果，x0/y0/x1/y1 是 PDF 坐标系的归一化值。
    """
    from src.parse.doc_converter import convert_docx_to_pdf

    pdf_path = convert_docx_to_pdf(docx_path, out_dir=out_dir, timeout=timeout)
    return parse_with_mineru(
        pdf_path,
        backend=backend,
        language=language,
        table_enable=table_enable,
        cluster_ports=cluster_ports,
    )
