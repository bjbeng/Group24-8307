"""标准号规范化：提取编号、去除年份、统一格式。

支持的家族（family）：
  GB/T, GB, Q/SY (QSY), TSG, AQ, SY/T, NB/T, SH/T, DL/T, HG/T, YB/T
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 匹配标准号（含或不含年份）
# 顺序重要：更具体的模式放前面
_CITATION_RE = re.compile(
    r"""
    (?:
        # GB/T  GB/Z  GB
        (?P<gb>GB(?:/[TZZ])?)\s*(\d+(?:\.\d+)?)
      | # Q/SY  QSY
        (?P<qsy>Q/?SY)\s*(\d+(?:\.\d+)?)
      | # TSG（可带字母前缀，如 TSG D7005 或 TSG 31）
        (?P<tsg>TSG)\s*([A-Z]?\d+(?:\.\d+)?)
      | # AQ
        (?P<aq>AQ)\s*(\d+(?:\.\d+)?)
      | # SY/T  SY
        (?P<sy>SY(?:/T)?)\s*(\d+(?:\.\d+)?)
      | # NB/T
        (?P<nb>NB/T)\s*(\d+(?:\.\d+)?)
      | # SH/T
        (?P<sh>SH/T)\s*(\d+(?:\.\d+)?)
      | # DL/T
        (?P<dl>DL/T)\s*(\d+(?:\.\d+)?)
      | # HG/T
        (?P<hg>HG/T)\s*(\d+(?:\.\d+)?)
    )
    # 可选年份：-2020 或 —2020（em-dash）
    (?:[—\-](?P<year>(?:19|20)\d{2}))?
    """,
    re.VERBOSE,
)

# 家族规范化映射
_FAMILY_MAP: dict[str, str] = {
    "GB/T": "GBT",
    "GB/Z": "GBZ",
    "GB/Z": "GBZ",
    "GB": "GB",
    "Q/SY": "QSY",
    "QSY": "QSY",
    "TSG": "TSG",
    "AQ": "AQ",
    "SY/T": "SYT",
    "SY": "SY",
    "NB/T": "NBT",
    "SH/T": "SHT",
    "DL/T": "DLT",
    "HG/T": "HGT",
}


@dataclass(frozen=True)
class Citation:
    number_raw: str        # "GB/T 21246-2020"
    number_normalized: str # "GBT21246"
    year: int | None       # 2020 或 None（文档未注年份）
    context: str           # 上下文片段（用于 evidence）


def normalize_number(raw: str) -> str:
    """将任意格式标准号规范化为无年份、无空格、大写的 key。

    Examples::
        normalize_number("GB/T 21246-2020")  -> "GBT21246"
        normalize_number("TSG D7005—2018")   -> "TSGD7005"
        normalize_number("Q/SY 1217")        -> "QSY1217"
    """
    raw = raw.strip()
    # 去掉年份后缀
    raw_no_year = re.sub(r"[—\-](?:19|20)\d{2}$", "", raw).strip()
    # 统一 family
    for pat, norm in sorted(_FAMILY_MAP.items(), key=lambda x: -len(x[0])):
        prefix = re.escape(pat)
        m = re.match(rf"^{prefix}\s*", raw_no_year, re.IGNORECASE)
        if m:
            rest = raw_no_year[m.end():].replace(" ", "").replace(".", ".")
            return norm + rest.upper()
    # fallback：直接去空格大写
    return re.sub(r"\s+", "", raw_no_year).upper()


def extract_citations(text: str) -> list[Citation]:
    """从文本中提取所有标准引用。"""
    results: list[Citation] = []
    seen: set[tuple[str, int | None]] = set()

    for m in _CITATION_RE.finditer(text):
        full_match = m.group(0)
        year_str = m.group("year")
        year = int(year_str) if year_str else None

        # 确定 family 和 number
        normalized = normalize_number(full_match)
        key = (normalized, year)
        if key in seen:
            continue
        seen.add(key)

        # 取前后 40 字作为 context
        start = max(0, m.start() - 40)
        end = min(len(text), m.end() + 40)
        context = text[start:end].replace("\n", " ").strip()

        results.append(Citation(
            number_raw=full_match.strip(),
            number_normalized=normalized,
            year=year,
            context=context,
        ))

    return results
