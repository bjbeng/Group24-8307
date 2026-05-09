"""`.doc` → `.docx` 转换。

python-docx 不能直接读老 Word 二进制 `.doc`；统一先用 LibreOffice headless 转 docx。
失败抛 `DocConversionError`，调用方决定回退（如手动转换或 antiword）。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path


log = logging.getLogger(__name__)


class DocConversionError(RuntimeError):
    """`.doc` 转换失败。"""


def _find_soffice() -> str:
    import os
    import sys

    # 显式指定路径优先（适配自定义安装目录）
    for env_key in ("SOFFICE_PATH", "LIBREOFFICE_PATH"):
        env_path = os.environ.get(env_key, "").strip().strip('"')
        if env_path and os.path.exists(env_path):
            return env_path

    for name in ("soffice", "libreoffice"):
        path = shutil.which(name)
        if path:
            return path

    # Windows 默认安装路径
    if sys.platform == "win32":
        local_app = os.environ.get("LOCALAPPDATA", "")
        for candidate in (
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            os.path.join(local_app, "Programs", "LibreOffice", "program", "soffice.exe") if local_app else "",
        ):
            if candidate and os.path.exists(candidate):
                return candidate

    raise DocConversionError(
        "未找到 LibreOffice。请安装：\n"
        "  Windows     : https://www.libreoffice.org/download/\n"
        "  Debian/Ubuntu: sudo apt install -y libreoffice\n"
        "  CentOS/RHEL : sudo yum install -y libreoffice\n"
        "  macOS       : brew install --cask libreoffice\n"
        "  Docker      : 见项目 Dockerfile（已内置）"
    )


def convert_doc_to_docx(
    src: str | Path,
    out_dir: str | Path | None = None,
    *,
    timeout: float = 60.0,
) -> Path:
    """把 `.doc` 转成 `.docx`，返回新文件路径。

    - 输入已经是 `.docx`/`.docm`：直接复制到 `out_dir` 后返回。
    - 输入是 `.doc`：调用 LibreOffice headless 转换。
    - 失败时抛 `DocConversionError`，调用方应有降级策略。
    """
    src_path = Path(src).resolve()
    if not src_path.exists():
        raise FileNotFoundError(f"源文件不存在: {src_path}")

    out_path = Path(out_dir).resolve() if out_dir else src_path.parent
    out_path.mkdir(parents=True, exist_ok=True)

    suffix = src_path.suffix.lower()
    if suffix in (".docx", ".docm"):
        dst = out_path / src_path.name
        if dst.resolve() != src_path:
            shutil.copy2(src_path, dst)
        return dst

    if suffix != ".doc":
        raise DocConversionError(f"不支持的扩展名: {suffix}")

    soffice = _find_soffice()
    cmd = [
        soffice,
        "--headless",
        "--convert-to",
        "docx",
        "--outdir",
        str(out_path),
        str(src_path),
    ]
    log.debug("Running: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise DocConversionError(f"LibreOffice 转换超时 (>{timeout}s)") from e

    if result.returncode != 0:
        raise DocConversionError(
            f"LibreOffice 退出码 {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    converted = out_path / (src_path.stem + ".docx")
    if not converted.exists():
        raise DocConversionError(
            f"LibreOffice 未生成预期文件: {converted}\nstdout: {result.stdout}"
        )
    return converted


def convert_docx_to_pdf(
    src: str | Path,
    out_dir: str | Path | None = None,
    *,
    timeout: float = 120.0,
) -> Path:
    """把 `.docx`/`.doc` 转成 `.pdf`，返回新文件路径。

    用于：DOCX 本身没有坐标，通过 LibreOffice 转 PDF 后用 MinerU 解析获取 bbox。
    LibreOffice headless 渲染会保留页面布局，PDF 有完整坐标系统。
    """
    src_path = Path(src).resolve()
    if not src_path.exists():
        raise FileNotFoundError(f"源文件不存在: {src_path}")

    out_path = Path(out_dir).resolve() if out_dir else src_path.parent
    out_path.mkdir(parents=True, exist_ok=True)

    suffix = src_path.suffix.lower()
    if suffix not in (".docx", ".docm", ".doc"):
        raise DocConversionError(f"不支持的扩展名（需要 .docx/.doc）: {suffix}")

    soffice = _find_soffice()

    # DOC/DOCX 先统一转成 docx（如果输入是 .doc）
    if suffix == ".doc":
        src_path = convert_doc_to_docx(src_path, out_dir)

    cmd = [
        soffice,
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(out_path),
        str(src_path),
    ]
    log.debug("Running: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise DocConversionError(f"LibreOffice 转 PDF 超时 (>{timeout}s)") from e

    if result.returncode != 0:
        raise DocConversionError(
            f"LibreOffice 转 PDF 退出码 {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    converted = out_path / (src_path.stem + ".pdf")
    if not converted.exists():
        raise DocConversionError(
            f"LibreOffice 未生成 PDF: {converted}\nstdout: {result.stdout}"
        )
    log.info("DOCX/DOC → PDF: %s → %s", src_path.name, converted.name)
    return converted
