"""从 YAML 种子文件加载标准版本元数据到 standard_versions 表。"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from src.store.repository import Repository
from src.standards_lib.normalizer import normalize_number

log = logging.getLogger(__name__)

_DEFAULT_YAML = Path(__file__).resolve().parent.parent.parent / "config" / "standards_versions.yaml"


def load_versions_from_yaml(repo: Repository, yaml_path: Path | None = None) -> int:
    """幂等导入；返回写入条数。"""
    path = yaml_path or _DEFAULT_YAML
    if not path.exists():
        log.warning("standards_versions.yaml 不存在，跳过: %s", path)
        return 0

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    entries = data.get("standards", [])
    n = 0
    for entry in entries:
        try:
            raw = entry["number_raw"]
            norm = entry.get("number_normalized") or normalize_number(raw)
            repo.upsert_standard_version(
                number_normalized=norm,
                number_raw=raw,
                latest_year=entry.get("latest_year"),
                title=entry.get("title", ""),
                status=entry.get("status", "current"),
                superseded_by=entry.get("superseded_by"),
                source=entry.get("source", "yaml"),
            )
            n += 1
        except Exception as e:
            log.warning("跳过条目 %s：%s", entry, e)

    log.info("standards_versions 导入 %d 条", n)
    return n
