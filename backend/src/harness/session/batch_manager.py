"""批量任务管理器：asyncio Queue + Semaphore，支持进度回调。"""
from __future__ import annotations
import asyncio
import datetime
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

@dataclass
class BatchJob:
    job_id: str
    doc_paths: list[str]
    status: str = "pending"      # pending / running / done / failed
    progress: int = 0
    total: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""

class BatchJobManager:
    """
    异步批量审核任务管理器。

    用法：
        mgr = BatchJobManager(audit_fn=my_audit, max_concurrent=3)
        job_id = await mgr.submit(["doc1.docx", "doc2.docx"])
        status = mgr.get_status(job_id)
    """

    def __init__(
        self,
        audit_fn: Callable[[str], Awaitable[dict[str, Any]]],
        max_concurrent: int = 5,
        on_progress: Callable[[str, int, int, dict[str, Any]], None] | None = None,
    ) -> None:
        self._audit_fn = audit_fn
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._on_progress = on_progress
        self._jobs: dict[str, BatchJob] = {}

    async def submit(self, doc_paths: list[str], job_id: str | None = None) -> str:
        import uuid
        if job_id is None:
            job_id = f"batch_{uuid.uuid4().hex[:8]}"
        job = BatchJob(
            job_id=job_id,
            doc_paths=list(doc_paths),
            total=len(doc_paths),
            started_at=datetime.datetime.now().isoformat(),
        )
        self._jobs[job_id] = job
        asyncio.create_task(self._run_job(job))
        return job_id

    async def _run_job(self, job: BatchJob) -> None:
        job.status = "running"
        tasks = [self._run_single(job, path) for path in job.doc_paths]
        await asyncio.gather(*tasks, return_exceptions=True)
        job.status = "done" if not job.errors else "failed"
        job.finished_at = datetime.datetime.now().isoformat()
        log.info("batch_done job=%s total=%d errors=%d", job.job_id, job.total, len(job.errors))

    async def _run_single(self, job: BatchJob, doc_path: str) -> None:
        async with self._semaphore:
            try:
                result = await self._audit_fn(doc_path)
                job.results.append(result)
            except Exception as e:
                log.error("batch单文档失败 [%s]: %s", doc_path, e)
                job.errors.append(f"{doc_path}: {e}")
                job.results.append({"doc_path": doc_path, "error": str(e)})
            finally:
                job.progress += 1
                if self._on_progress:
                    try:
                        self._on_progress(job.job_id, job.progress, job.total, job.results[-1])
                    except Exception:
                        pass

    def get_status(self, job_id: str) -> dict[str, Any] | None:
        job = self._jobs.get(job_id)
        if not job:
            return None
        return {
            "job_id": job.job_id,
            "status": job.status,
            "progress": job.progress,
            "total": job.total,
            "errors": job.errors,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
        }

    def list_jobs(self) -> list[dict[str, Any]]:
        return [self.get_status(jid) for jid in self._jobs]
