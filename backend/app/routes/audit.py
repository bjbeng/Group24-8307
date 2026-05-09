from __future__ import annotations
import asyncio
import logging
import time
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from app.auth.deps import current_user, verify_csrf
from app.config import get_settings
from app.tasks.queue import get_task, list_tasks, submit_task
from app.security import safe_upload_path
from app.tracing.hooks import (
    on_pipeline_start, on_ingest_done, on_pipeline_done, on_pipeline_error,
)

_RESULTS_DIR = Path("./data/results")

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/audit", tags=["audit"])


def _build_task_payload(t, *, include_result: bool) -> dict[str, object]:
    return {
        "task_id": t.task_id,
        "scenario": t.scenario,
        "mode": t.mode,
        "status": t.status,
        "progress": t.progress,
        "total": t.total,
        "summary": t.summary,
        "result_ready": t.result is not None,
        "result": t.result if include_result else None,
        "error": t.error,
    }


# ── 内部辅助 ──────────────────────────────────────────────────────────────────

def _load_audit_json(task_id: str) -> dict:
    """从结果目录加载 audit JSON，找到第一个 *_audit.json 文件。"""
    task_dir = _RESULTS_DIR / task_id
    if not task_dir.is_dir():
        raise HTTPException(404, f"任务结果目录不存在: {task_id}")

    candidates = list(task_dir.glob("*_audit.json"))
    if not candidates:
        # 尝试在根结果目录查找（旧的 task_id 即 doc_id 场景）
        root_candidates = list(_RESULTS_DIR.glob(f"{task_id}_*_audit.json"))
        if not root_candidates:
            raise HTTPException(404, f"审核结果文件不存在: {task_id}")
        audit_path = root_candidates[0]
    else:
        audit_path = candidates[0]

    try:
        import json as _json
        return _json.loads(audit_path.read_text(encoding="utf-8"))
    except _json.JSONDecodeError as e:
        log.error("JSON 解析失败 task_id=%s path=%s error=%s", task_id, audit_path, e)
        raise HTTPException(500, f"审核结果 JSON 解析失败: {e}")


def _load_repo() -> "Repository":
    """获取 Repository 实例（避免循环 import）。"""
    from src.store.repository import Repository
    s = get_settings()
    return Repository(s.engine_db_path)


def _build_engine_config(scenario: str = "s1") -> dict:
    """
    组装审核引擎配置：
    - paths / parse / chunk / retrieve / audit 读引擎默认值
    - llm 块按场景注入（s1: A=DeepSeek/B=Qwen, s2: A=Qwen/B=Gemini）
    """
    from src.config import get_default_config
    s = get_settings()

    cfg = get_default_config()
    cfg["paths"]["db_path"] = s.engine_db_path

    # 把 .env 里的场景/角色配置写入引擎 llm 块
    cfg["llm"] = s.build_engine_llm_config(scenario)
    return cfg


async def _do_audit(
    doc_path: str,
    config_override: dict | None = None,
    progress_cb=None,
) -> dict:
    """审核阶段：s1 走 AuditPipeline，s2 走 LabelPipeline(scenario='s2')。"""
    scenario = (config_override or {}).get("scenario", "s1")
    log.info("[_do_audit] scenario=%s task_id=%s", scenario,
             (config_override or {}).get("_task_id", ""))
    cfg = _build_engine_config(scenario)
    if config_override:
        rule_set = config_override.get("rule_set_id")
        if rule_set:
            cfg["rule_set_id"] = rule_set

    loop = asyncio.get_event_loop()
    task_id = config_override.get("_task_id", "") if config_override else ""
    doc_id = Path(doc_path).stem

    def _run():
        on_pipeline_start(task_id, doc_id, scenario)
        t0 = time.perf_counter()
        log.info("audit START task=%s doc=%s scenario=%s", task_id[:8], doc_id, scenario)

        if scenario == "s2":
            # s2 使用 LabelPipeline（含 I1-I8 + L1-L6 视觉/文本 Agent）
            from src.harness.pipeline.label_pipeline import LabelPipeline
            pipe = LabelPipeline(config=cfg, scenario="s2")
            try:
                result = pipe.run(doc_path, progress_cb=progress_cb)
                elapsed = (time.perf_counter() - t0) * 1000
                on_pipeline_done(task_id, doc_id, elapsed, len(result.dimensions))
                log.info("audit(s2) DONE task=%s elapsed=%.0fms verdict=%s",
                         task_id[:8], elapsed, result.overall_verdict)
                result_dict = result.to_dict()
                result_dict["pipeline"] = "audit"  # 标记为 audit 模式
                return result_dict
            except Exception as e:
                on_pipeline_error(task_id, doc_id, str(e))
                log.error("audit(s2) FAIL task=%s error=%s", task_id[:8], e)
                raise
            finally:
                pipe.close()
        else:
            # s1 走原有 AuditPipeline
            from src.pipeline.audit import AuditPipeline
            from src.output.annotator import write_outputs
            pipe = AuditPipeline(config=cfg)
            try:
                result = pipe.run(doc_path, progress_cb=progress_cb)
                elapsed = (time.perf_counter() - t0) * 1000
                on_pipeline_done(task_id, doc_id, elapsed, len(result.dimensions))
                log.info("audit(s1) DONE task=%s elapsed=%.0fms verdict=%s",
                         task_id[:8], elapsed, result.overall_verdict)

                out_dir = _RESULTS_DIR / (task_id or result.doc_id)
                src_for_annotate = result.converted_docx_path or doc_path
                try:
                    artifacts = write_outputs(src_for_annotate, result.to_dict(), out_dir)
                    log.info("audit outputs written: %s", [str(p) for p in artifacts.values()])
                except Exception as exc:
                    log.warning("write_outputs 失败（不影响任务结果）: %s", exc)

                result_dict = result.to_dict()
                result_dict["output_dir"] = str(out_dir)
                return result_dict
            except Exception as e:
                on_pipeline_error(task_id, doc_id, str(e))
                log.error("audit(s1) FAIL task=%s error=%s", task_id[:8], e)
                raise
            finally:
                pipe.close()

    return await loop.run_in_executor(None, _run)


async def _do_label(
    doc_path: str,
    config_override: dict | None = None,
    progress_cb=None,
) -> dict:
    """在线程池里同步运行 LabelPipeline（打标阶段，A‖B → Critic）。"""
    scenario = (config_override or {}).get("scenario", "s1")
    cfg = _build_engine_config(scenario)

    loop = asyncio.get_event_loop()

    task_id = config_override.get("_task_id", "") if config_override else ""
    doc_id = Path(doc_path).stem

    def _run():
        on_pipeline_start(task_id, doc_id, scenario)
        t0 = time.perf_counter()
        log.info("label  START task=%s doc=%s scenario=%s", task_id[:8], doc_id, scenario)
        from src.harness.pipeline.label_pipeline import LabelPipeline
        pipe = LabelPipeline(config=cfg, scenario=scenario)
        try:
            result = pipe.run(doc_path, progress_cb=progress_cb)
            elapsed = (time.perf_counter() - t0) * 1000
            on_pipeline_done(task_id, doc_id, elapsed, len(result.dimensions))
            log.info("label  DONE  task=%s doc=%s elapsed=%.0fms", task_id[:8], doc_id, elapsed)
            return result.to_dict()
        except Exception as e:
            on_pipeline_error(task_id, doc_id, str(e))
            log.error("label  FAIL  task=%s doc=%s error=%s", task_id[:8], doc_id, e)
            raise
        finally:
            pipe.close()

    return await loop.run_in_executor(None, _run)


# ── REST 接口 ─────────────────────────────────────────────────────────────────

@router.post("/start", dependencies=[Depends(verify_csrf)])
async def start_audit(
    body: dict,
    user_id: str = Depends(current_user),
) -> JSONResponse:
    """
    启动审核任务。

    body 字段：
      file_name  : 已上传的文件名（必填）
      scenario   : "s1"（作业书）| "s2"（风险管控），默认 s1
      mode       : "audit"（审核）| "label"（打标），默认 audit
      rule_set_id: 可选，指定审核规则集 ID
    """
    s = get_settings()
    file_name = body.get("file_name", "")
    if not file_name:
        raise HTTPException(400, "file_name 不能为空")

    dest = safe_upload_path(s.upload_dir, user_id, file_name)
    if not dest.exists():
        raise HTTPException(404, f"文件不存在: {file_name}")

    scenario = body.get("scenario", "s1")
    mode = body.get("mode") or "audit"  # 两个场景默认均走 audit
    config = {
        "scenario": scenario,
        "mode": mode,
        "rule_set_id": body.get("rule_set_id"),
    }

    fn = _do_label if mode == "label" else _do_audit
    task_id = await submit_task(
        fn, str(dest), config,
        user_id=user_id, file_name=file_name,
    )
    log.info("submit task=%s user=%s file=%s scenario=%s mode=%s",
             task_id[:8], user_id, file_name, scenario, mode)

    return JSONResponse({
        "task_id": task_id,
        "scenario": scenario,
        "mode": mode,
    })


@router.get("/{task_id}")
async def get_audit_status(
    task_id: str,
    include_result: bool = False,
    user_id: str = Depends(current_user),
) -> JSONResponse:
    t = get_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    return JSONResponse(_build_task_payload(t, include_result=include_result))


@router.get("/{task_id}/summary")
async def get_audit_summary(
    task_id: str,
    user_id: str = Depends(current_user),
) -> JSONResponse:
    t = get_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    return JSONResponse(_build_task_payload(t, include_result=False))


@router.get("/{task_id}/result")
async def get_audit_result(
    task_id: str,
    user_id: str = Depends(current_user),
) -> JSONResponse:
    t = get_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    return JSONResponse(_build_task_payload(t, include_result=True))


@router.post("/batch", dependencies=[Depends(verify_csrf)])
async def batch_audit(
    body: dict,
    user_id: str = Depends(current_user),
) -> JSONResponse:
    """批量审核，所有文件使用相同场景/模式。"""
    s = get_settings()
    file_names = body.get("file_names", [])
    if not file_names:
        raise HTTPException(400, "file_names 不能为空")

    scenario = body.get("scenario", "s1")
    mode = body.get("mode") or "audit"  # 两个场景默认均走 audit
    fn = _do_label if mode == "label" else _do_audit

    task_ids = []
    for name in file_names:
        dest = safe_upload_path(s.upload_dir, user_id, name)
        if not dest.exists():
            raise HTTPException(404, f"文件不存在: {name}")
        tid = await submit_task(
            fn, str(dest),
            {"scenario": scenario, "mode": mode, "user_id": user_id},
            user_id=user_id, file_name=name,
        )
        task_ids.append(tid)

    return JSONResponse({
        "task_ids": task_ids,
        "total": len(task_ids),
        "scenario": scenario,
        "mode": mode,
    })


# ── Finding 定位 API ───────────────────────────────────────────────────────────

@router.get("/findings/{task_id}/locations")
async def get_finding_locations(
    task_id: str,
    dimension: str | None = None,
    severity: str | None = None,
    user_id: str = Depends(current_user),
) -> JSONResponse:
    """
    获取审核结果的 Finding 定位列表。

    query 参数：
      dimension : 可选，按维度过滤（如 C1_structure）
      severity  : 可选，按严重程度过滤（high / medium / low）
    """
    t = get_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    if t.user_id != user_id:
        raise HTTPException(403, "无权访问此任务")

    audit_data = _load_audit_json(task_id)
    repo = _load_repo()

    all_findings: list[dict] = []
    for dim_key, dim_data in audit_data.get("dimensions", {}).items():
        for f in dim_data.get("findings", []):
            f_copy = dict(f)
            f_copy["dimension"] = dim_key
            all_findings.append(f_copy)

    # 过滤
    if dimension:
        all_findings = [f for f in all_findings if f.get("dimension") == dimension]
    if severity:
        all_findings = [f for f in all_findings if f.get("severity") == severity]

    # 补全 chunk 上下文（从 SQLite 读取）
    enriched: list[dict] = []
    for f in all_findings:
        chunk_id = f.get("chunk_id")
        chunk_info: dict = {}
        if chunk_id:
            chunk_info = repo.get_chunk(chunk_id) or {}

        highlight_text = ""
        if chunk_info.get("content"):
            anchor = f.get("anchor_text", "")
            if anchor and anchor in chunk_info["content"]:
                idx = chunk_info["content"].index(anchor)
                start = max(0, idx - 20)
                end = min(len(chunk_info["content"]), idx + len(anchor) + 20)
                highlight_text = chunk_info["content"][start:end]
            else:
                highlight_text = (chunk_info.get("content") or "")[:100]

        enriched.append({
            "dimension":       f.get("dimension"),
            "severity":        f.get("severity"),
            "chunk_id":        chunk_id,
            "section_path":    f.get("section_path") or chunk_info.get("section_path"),
            "anchor_text":     f.get("anchor_text") or chunk_info.get("anchor_text"),
            "paragraph_index": f.get("paragraph_index") if f.get("paragraph_index", -1) >= 0
                               else chunk_info.get("paragraph_index"),
            "highlight_text":  highlight_text,
            "description":     f.get("description"),
            "rule_id":         f.get("rule_id"),
            "problem_type":    f.get("problem_type"),
        })

    # 统计
    by_severity: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for f in all_findings:
        sev = f.get("severity", "")
        if sev in by_severity:
            by_severity[sev] += 1

    # 目录导航（从 chunks 表聚合）
    doc_id = audit_data.get("doc_id", "")
    section_map: dict[str, dict] = {}
    for row in repo.get_chunks_by_doc(doc_id):
        sp = row.get("section_path")
        if sp and sp not in section_map:
            section_map[sp] = {
                "section_path": sp,
                "title":        row.get("title"),
                "level":        len(sp.split(".")) if sp else 1,
                "page_number":  row.get("page_start"),
                "chunk_id":     row.get("chunk_id"),
            }

    sections = sorted(section_map.values(), key=lambda x: x["section_path"])

    return JSONResponse({
        "task_id":        task_id,
        "findings":       enriched,
        "navigation": {
            "sections":        sections,
            "total_findings":  len(enriched),
            "by_severity":     by_severity,
        },
    })


@router.get("/document/{doc_id}/sections")
async def get_document_sections(
    doc_id: str,
    user_id: str = Depends(current_user),
) -> JSONResponse:
    """
    获取文档的章节目录结构（用于导航侧边栏）。
    """
    repo = _load_repo()
    chunks = repo.get_chunks_by_doc(doc_id)

    if not chunks:
        raise HTTPException(404, f"文档不存在或未解析: {doc_id}")

    # 按 section_path 聚合
    section_map: dict[str, dict] = {}
    for row in chunks:
        sp = row.get("section_path")
        if sp and sp not in section_map:
            section_map[sp] = {
                "section_path": sp,
                "title":        row.get("title"),
                "level":        len(sp.split(".")) if sp else 1,
                "page_number":  row.get("page_start"),
                "chunk_id":     row.get("chunk_id"),
                "chunk_type":   row.get("chunk_type"),
            }
        elif sp and row.get("chunk_type") == "heading" and row.get("title"):
            # 标题优先
            section_map[sp]["title"] = row.get("title")

    sections = sorted(section_map.values(), key=lambda x: x["section_path"])

    return JSONResponse({
        "doc_id":   doc_id,
        "sections": sections,
    })


@router.get("/document/{doc_id}/section/{section_path}/findings")
async def get_section_findings(
    doc_id: str,
    section_path: str,
    user_id: str = Depends(current_user),
) -> JSONResponse:
    """
    获取指定章节下的所有 findings（用于点击章节时高亮相关问题）。
    返回该章节的 chunk 关联的所有维度问题。
    """
    repo = _load_repo()
    chunks = repo.get_chunks_by_doc(doc_id)

    # 找到该 section_path 下的所有 chunk_ids
    target_chunks = [c for c in chunks if c.get("section_path") == section_path]
    if not target_chunks:
        raise HTTPException(404, f"章节不存在: {section_path}")

    chunk_ids = {c["chunk_id"] for c in target_chunks if c.get("chunk_id")}

    # 全量 findings 需要遍历任务目录
    # 策略：找到该 doc_id 对应的最新 task
    task_dir = None
    for td in _RESULTS_DIR.iterdir():
        if td.is_dir():
            audit_files = list(td.glob("*_audit.json"))
            for af in audit_files:
                try:
                    import json as _json
                    data = _json.loads(af.read_text(encoding="utf-8"))
                    if data.get("doc_id") == doc_id:
                        task_dir = td
                        audit_data = data
                        break
                except Exception:
                    continue
        if task_dir:
            break

    if not task_dir:
        return JSONResponse({
            "doc_id":       doc_id,
            "section_path": section_path,
            "findings":     [],
        })

    all_findings: list[dict] = []
    for dim_key, dim_data in audit_data.get("dimensions", {}).items():
        for f in dim_data.get("findings", []):
            if f.get("chunk_id") in chunk_ids:
                f_copy = dict(f)
                f_copy["dimension"] = dim_key
                all_findings.append(f_copy)

    # 补全 highlight_text
    enriched: list[dict] = []
    for f in all_findings:
        chunk_info = repo.get_chunk(f.get("chunk_id", "")) or {}
        highlight = ""
        if chunk_info.get("content"):
            anchor = f.get("anchor_text", "")
            if anchor and anchor in chunk_info["content"]:
                idx = chunk_info["content"].index(anchor)
                start = max(0, idx - 20)
                end = min(len(chunk_info["content"]), idx + len(anchor) + 20)
                highlight = chunk_info["content"][start:end]
            else:
                highlight = (chunk_info.get("content") or "")[:100]

        enriched.append({
            "dimension":       f.get("dimension"),
            "severity":        f.get("severity"),
            "chunk_id":        f.get("chunk_id"),
            "section_path":    section_path,
            "anchor_text":     f.get("anchor_text"),
            "paragraph_index": f.get("paragraph_index"),
            "highlight_text":  highlight,
            "description":     f.get("description"),
            "rule_id":         f.get("rule_id"),
            "problem_type":    f.get("problem_type"),
        })

    return JSONResponse({
        "doc_id":       doc_id,
        "section_path": section_path,
        "findings":     enriched,
        "total":        len(enriched),
    })


# ── 下载接口 ──────────────────────────────────────────────────────────────────

_DOWNLOAD_TYPES = {
    "report":    ("_report.md",     "text/markdown; charset=utf-8"),
    "annotated": ("_annotated.docx",
                  "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "json":      ("_audit.json",    "application/json; charset=utf-8"),
}


@router.get("/{task_id}/download/{file_type}")
async def download_audit_artifact(
    task_id: str,
    file_type: str,
    user_id: str = Depends(current_user),
) -> FileResponse:
    """下载审核产物。

    file_type: report（Markdown 报告）| annotated（带批注 DOCX）| json（原始 JSON）
    """
    if file_type not in _DOWNLOAD_TYPES:
        raise HTTPException(400, f"不支持的文件类型: {file_type}，可选 report / annotated / json")

    t = get_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    if t.user_id != user_id:
        raise HTTPException(403, "无权访问此任务")
    if t.status != "done":
        raise HTTPException(409, f"任务尚未完成（当前状态: {t.status}）")

    suffix, media_type = _DOWNLOAD_TYPES[file_type]
    out_dir = _RESULTS_DIR / task_id

    # 文件名 = doc_id + suffix，遍历目录找第一个匹配
    candidates = list(out_dir.glob(f"*{suffix}")) if out_dir.exists() else []
    if not candidates:
        raise HTTPException(404, f"产物文件不存在（{suffix}），请确认审核已完成且文件已生成")

    target = candidates[0]
    filename = target.name
    return FileResponse(
        path=str(target),
        media_type=media_type,
        filename=filename,
    )
