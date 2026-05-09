"""图片预分析 pipeline：对每张 ImageChunk 调一次 VL 模型，回填 description + analysis。

设计：
- 单次审核中每张图只调一次 VL（结果存到 ImageChunk.analysis），后续 I1-I8
  Agent 直接读 analysis 字段，无需重复调用
- 失败的图：description="" / analysis={"_error": ...}，下游 Agent 会兜底为 uncertain
- ``unknown`` 类型的图只生成简单 description，不强行做结构化分析
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from src.agents.base import parse_json_response
from src.agents.vision_prompts import DESC_PROMPT, get_analysis_prompt
from src.chunk.image_chunk import ImageChunk
from src.llm.provider import LLMProvider


log = logging.getLogger(__name__)

_DEBUG_VISION = os.environ.get("INDUSTRY_DEBUG_VISION", "").strip().lower() in {"1", "true", "yes", "on"}
_DEBUG_VISION_DIR = os.environ.get("INDUSTRY_DEBUG_VISION_DIR", "").strip()


def _context_hint(img: ImageChunk) -> str:
    ctx = img.context or {}
    lines = [
        f"section_path: {img.section_path or '(none)'}",
        f"section_title: {img.title or '(none)'}",
        f"prev_heading: {ctx.get('prev_heading') or '(none)'}",
        f"prev_text: {ctx.get('prev_text') or '(none)'}",
        f"next_heading: {ctx.get('next_heading') or '(none)'}",
        f"next_text: {ctx.get('next_text') or '(none)'}",
    ]
    return "\n".join(lines)

def _maybe_dump_vision_input(
    *,
    kind: str,
    img: ImageChunk,
    prompt: str,
    system: str | None = None,
) -> None:
    """调试：展示/落盘 VL 输入（不包含 base64 图片内容）。"""
    if not _DEBUG_VISION and not _DEBUG_VISION_DIR:
        return

    ctx = _context_hint(img)
    header = (
        f"[VISION_INPUT] kind={kind} image_type={img.image_type} chunk_id={img.chunk_id}\n"
        f"image_path={img.image_path}\n"
        f"section_path={img.section_path}\n"
        f"title={img.title}\n"
    )
    body = (
        (f"SYSTEM:\n{system}\n\n" if system else "")
        + "CONTEXT_HINT:\n"
        + ctx
        + "\n\nPROMPT:\n"
        + prompt
        + "\n"
    )

    if _DEBUG_VISION:
        # 控制台展示：避免太长，只截断 prompt
        log.info(
            "[VisionDebug] %s image=%s type=%s prompt_len=%d",
            kind,
            img.image_path,
            img.image_type,
            len(prompt),
        )
        log.info("[VisionDebug] %s context_hint:\n%s", kind, ctx)
        log.info("[VisionDebug] %s prompt (head 1200 chars):\n%s", kind, prompt[:1200])

    if _DEBUG_VISION_DIR:
        try:
            out_dir = Path(_DEBUG_VISION_DIR)
            out_dir.mkdir(parents=True, exist_ok=True)
            safe_id = (img.chunk_id or "unknown").replace("/", "_").replace("\\", "_")
            p = out_dir / f"{safe_id}__{kind}.txt"
            p.write_text(header + "\n" + body, encoding="utf-8")
        except Exception as e:
            log.warning("[VisionDebug] dump failed: %s", e)


def _gen_description(
    provider: LLMProvider,
    vision_model: str,
    img: ImageChunk,
    *,
    timeout: float | None = None,
) -> str:
    try:
        prompt = f"{DESC_PROMPT}\n\n## 图片上下文\n{_context_hint(img)}"
        _maybe_dump_vision_input(kind="desc", img=img, prompt=prompt, system=None)
        return provider.call_vision(
            image_path=img.image_path,
            prompt=prompt,
            model=vision_model,
            temperature=0.0,
            max_tokens=200,
            timeout=timeout,
        ).strip()
    except Exception as e:
        log.warning("description 生成失败 (%s): %s", img.image_path, e)
        return ""


def _gen_analysis(
    provider: LLMProvider,
    vision_model: str,
    img: ImageChunk,
    *,
    timeout: float | None = None,
) -> dict[str, Any]:
    sys_user = get_analysis_prompt(img.image_type)
    if sys_user is None:
        return {}
    system, user = sys_user
    prompt = f"{user}\n\n## 图片上下文\n{_context_hint(img)}"
    _maybe_dump_vision_input(kind="analysis", img=img, prompt=prompt, system=system)
    try:
        raw = provider.call_vision(
            image_path=img.image_path,
            prompt=prompt,
            model=vision_model,
            temperature=0.0,
            max_tokens=1200,
            timeout=timeout,
            system=system,
        )
    except Exception as e:
        log.warning("analysis 生成失败 (%s, %s): %s", img.image_path, img.image_type, e)
        return {"_error": str(e)}
    parsed = parse_json_response(raw)
    return parsed or {"_raw": raw[:500]}


def analyze_all_images(
    provider: LLMProvider,
    vision_model: str,
    image_chunks: list[ImageChunk],
    *,
    timeout: float | None = None,
    skip_unknown: bool = False,
) -> list[ImageChunk]:
    """对所有 ImageChunk 顺序调用 VL，回填 description + analysis。

    in-place 修改并返回同一个列表（也便于链式调用）。

    参数：
    - skip_unknown: True 时不为 ``image_type=='unknown'`` 的图调用 VL（节省 token）
    """
    for img in image_chunks:
        if not img.image_path:
            continue
        if img.image_type == "unknown" and skip_unknown:
            continue

        if not img.description:
            img.description = _gen_description(
                provider, vision_model, img, timeout=timeout
            )

        if not img.analysis:
            img.analysis = _gen_analysis(
                provider, vision_model, img,
                timeout=timeout,
            )

    return image_chunks
