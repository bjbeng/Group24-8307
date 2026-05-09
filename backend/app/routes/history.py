from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from app.auth.deps import current_user
from app.tasks.queue import list_tasks, delete_task

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("")
async def get_history(
    limit: int = 50,
    user_id: str = Depends(current_user),
) -> JSONResponse:
    tasks = list_tasks(user_id=user_id, limit=limit)
    return JSONResponse({
        "tasks": [
            {
                "task_id": t.task_id,
                "file_name": t.file_name,
                "scenario": t.scenario,
                "mode": t.mode,
                "status": t.status,
                "progress": t.progress,
                "total": t.total,
                "created_at": t.created_at,
                "finished_at": t.finished_at,
                "error": t.error,
            }
            for t in tasks
        ],
        "total": len(tasks),
    })


@router.delete("/{task_id}")
async def remove_history(
    task_id: str,
    user_id: str = Depends(current_user),
) -> JSONResponse:
    deleted = delete_task(task_id=task_id, user_id=user_id)
    if not deleted:
        raise HTTPException(404, "任务不存在或无权限删除")
    return JSONResponse({"ok": True})
