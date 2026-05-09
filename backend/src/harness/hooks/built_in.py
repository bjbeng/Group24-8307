"""内置钩子：日志、验证、缓存、secret 扫描。"""
from __future__ import annotations
import json
import logging
import re
import time
from typing import Any
from .registry import hook

log = logging.getLogger(__name__)

# ── pre_tool_call ────────────────────────────────────────────────────────────

@hook("pre_tool_call")
def log_tool_invocation(tool_name: str, params: dict[str, Any]) -> None:
    """记录工具调用审计日志。"""
    log.debug("tool_invoke tool=%s params=%s", tool_name, list(params.keys()))

@hook("pre_tool_call")
def validate_chunk_id_format(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    """chunk_id 参数格式校验（只含字母数字下划线连字符）。"""
    chunk_id = params.get("chunk_id") or params.get("source_chunk_id") or params.get("body_chunk_id")
    if chunk_id and not re.match(r'^[\w\-\.]+$', str(chunk_id)):
        raise ValueError(f"非法 chunk_id 格式: {chunk_id}")
    return params

# ── post_tool_call ───────────────────────────────────────────────────────────

@hook("post_tool_call")
def validate_non_empty_result(tool_name: str, result: Any) -> Any:
    """FTS 检索工具返回空列表时打 warning（方便调试），不阻断流程。"""
    if tool_name in ("fts_search", "get_chunks_by_dimension") and isinstance(result, list) and not result:
        log.warning("工具 [%s] 返回空列表，可能标准库未初始化或维度路由未命中", tool_name)
    return result

# ── pre_agent_run ────────────────────────────────────────────────────────────

@hook("pre_agent_run")
def log_agent_start(role: str, dimension: str, doc_id: str) -> None:
    log.info("agent_start role=%s dim=%s doc=%s ts=%s", role, dimension, doc_id,
             time.strftime("%H:%M:%S"))

@hook("pre_agent_run")
def check_context_not_empty(role: str, dimension: str, doc_id: str, context: Any = None) -> None:
    if context is not None:
        chunks = getattr(context, "chunks", [])
        if not chunks:
            log.warning("agent [%s/%s] 上下文 chunks 为空，审核可能不准确", role, dimension)

# ── post_agent_run ───────────────────────────────────────────────────────────

@hook("post_agent_run")
def log_agent_result(role: str, dimension: str, result: Any) -> None:
    verdict = getattr(result, "verdict", None) or (
        result.get("verdict") if isinstance(result, dict) else "?"
    )
    conf = getattr(result, "confidence", None) or (
        result.get("confidence") if isinstance(result, dict) else "?"
    )
    log.info("agent_done role=%s dim=%s verdict=%s confidence=%s", role, dimension, verdict, conf)

@hook("post_agent_run")
def auto_flag_low_confidence(role: str, dimension: str, result: Any) -> Any:
    """confidence < 50 自动加 need_human_review=True。"""
    if not isinstance(result, dict):
        return result
    conf = result.get("confidence", 100)
    if isinstance(conf, (int, float)) and conf < 50 and not result.get("need_human_review"):
        result = dict(result)
        result["need_human_review"] = True
        log.debug("auto_flag: confidence=%s → need_human_review=True [%s/%s]", conf, role, dimension)
    return result

# ── pre_commit ───────────────────────────────────────────────────────────────

_SECRET_PATTERNS = [
    re.compile(r'(?i)(api[_\-]?key|secret[_\-]?key|password|passwd|token)\s*[=:]\s*\S{8,}'),
    re.compile(r'sk-[A-Za-z0-9]{20,}'),
    re.compile(r'eyJ[A-Za-z0-9_\-]{20,}'),  # JWT
]

@hook("pre_commit")
def check_no_secrets_in_findings(result: Any) -> None:
    """防止 LLM 幻觉把 API key / 密码等写进 findings.evidence。"""
    findings = []
    if isinstance(result, dict):
        findings = result.get("findings") or []
    elif hasattr(result, "findings"):
        findings = result.findings or []
    for f in findings:
        evidence = (f.get("evidence") if isinstance(f, dict) else getattr(f, "evidence", "")) or ""
        for pat in _SECRET_PATTERNS:
            if pat.search(evidence):
                raise ValueError(f"findings.evidence 疑似包含敏感信息，阻断写入: {evidence[:50]}")

# ── post_batch ───────────────────────────────────────────────────────────────

@hook("post_batch")
def log_batch_summary(batch_id: str, results: list[dict[str, Any]] | None = None) -> None:
    results = results or []
    total = len(results)
    human_review = sum(1 for r in results if r.get("need_human_review"))
    fail_count = sum(1 for r in results if r.get("overall_verdict") == "fail")
    log.info("batch_done id=%s total=%d human_review=%d fail=%d", batch_id, total, human_review, fail_count)
