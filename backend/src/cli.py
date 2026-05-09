"""命令行入口。

用法：
    python -m src.cli audit <doc_path> [--out result.json] [--config config/default.yaml]
    python -m src.cli label <doc_path> [--scenario s1|s2] [--out result.json]
    python -m src.cli ingest-chroma [--force]   # 重建 ChromaDB（含 LLM summary）
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

from src.config import get_default_config, load_config
from src.output import write_audit_json, write_outputs
from src.pipeline.audit import AuditPipeline
from src.harness.pipeline.label_pipeline import LabelPipeline


log = logging.getLogger("industry_agent")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def _build_pipeline(action: str, config_path: str | None, scenario: str = "s1"):
    cfg = load_config(config_path) if config_path else get_default_config()
    if action == "audit":
        return AuditPipeline(cfg), cfg
    if action == "label":
        return LabelPipeline(cfg, scenario=scenario), cfg  # type: ignore[arg-type]
    raise ValueError(f"未知动作: {action}")


def _summarise_label(result) -> tuple[str, int, bool]:
    """从 LabelResult.dimensions 推导 overall_verdict / score / need_review。"""
    verdicts = [r.verdict for r in result.dimensions.values()]
    scores = [r.score or 0 for r in result.dimensions.values()]
    need_review = any(r.need_human_review for r in result.dimensions.values())
    total = sum(scores)
    if not verdicts:
        return "uncertain", 0, need_review
    if "fail" in verdicts:
        return "fail", total, need_review
    if all(v == "pass" for v in verdicts):
        return "pass", total, need_review
    if "uncertain" in verdicts:
        return "uncertain", total, need_review
    return "partial", total, need_review


def main(argv: list[str] | None = None) -> int:
    # 单独的命令：无 doc_path，如 ingest-chroma
    if argv and argv[0] == "ingest-chroma":
        import argparse as _argparse, json as _json
        p = _argparse.ArgumentParser()
        p.add_argument("--force", action="store_true")
        a = p.parse_args(argv[1:])
        from src.standards_lib.ingest_chroma import ingest_all
        results = ingest_all(force=a.force)
        print("ChromaDB 导入结果:")
        for k, v in results.items():
            print(f"  {k}: {v} chunks")
        return 0

    parser = argparse.ArgumentParser(prog="industry-agent")
    parser.add_argument("action", choices=["audit", "label"], help="审核或打标")
    parser.add_argument("doc_path", help="待处理文档路径（.doc/.docx）")
    parser.add_argument("--out", help="输出目录（audit 模式）或 JSON 路径（label 模式）")
    parser.add_argument("--config", help="自定义配置 YAML")
    parser.add_argument("--report-only", action="store_true",
                        help="audit 模式：仅生成 JSON + 报告，跳过带批注 DOCX")
    parser.add_argument("--scenario", choices=["s1", "s2"], default="s1",
                        help="打标场景：s1=作业书（文本），s2=风险管控方案（文本+图片）")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)
    doc_path = Path(args.doc_path).resolve()
    if not doc_path.exists():
        log.error("文件不存在: %s", doc_path)
        return 2

    pipe, cfg = _build_pipeline(args.action, args.config, args.scenario)
    try:
        result = pipe.run(doc_path)
    finally:
        pipe.close()

    print(f"[{args.action}] {result.doc_name}")
    print(f"  doc_id: {result.doc_id}")

    if args.action == "audit":
        print(f"  overall_verdict: {result.overall_verdict}")
        print(f"  overall_score:   {result.overall_score}")
        if result.need_human_review:
            print("  [!] 需要人工复核")

        # 输出目录：--out 指定则当目录使用，否则用 results_dir/<doc_id>
        out_dir = Path(args.out) if args.out else (
            Path(cfg["paths"]["results_dir"]) / result.doc_id
        )

        if args.report_only:
            # 仅输出 JSON + Markdown 报告
            import json as _json
            out_dir.mkdir(parents=True, exist_ok=True)
            json_path = out_dir / f"{result.doc_id}_audit.json"
            json_path.write_text(
                _json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            from src.output.annotator import generate_markdown_report
            md_path = out_dir / f"{result.doc_id}_report.md"
            md_path.write_text(generate_markdown_report(result.to_dict()), encoding="utf-8")
            artifacts = {"json": json_path, "markdown": md_path}
        else:
            # 选择批注源：优先用转换后的 .docx，否则用原始路径（.docx 直接输入）
            src_for_annotate = result.converted_docx_path or str(doc_path)
            artifacts = write_outputs(src_for_annotate, result.to_dict(), out_dir)

        print(f"  output_dir: {out_dir}")
        for kind, p in artifacts.items():
            print(f"    [{kind}] {p.name}")
    else:
        verdict, score, need_review = _summarise_label(result)
        print(f"  scenario:        {result.scenario}")
        print(f"  overall_verdict: {verdict}")
        print(f"  overall_score:   {score}")
        if need_review:
            print("  [!] 需要人工复核")

        out_path = Path(args.out) if args.out else (
            Path(cfg["paths"]["results_dir"]) / f"{result.doc_id}_{args.action}.json"
        )

        # 赛题格式输出（包含文档基本信息 metadata）
        from src.output.contest_formatter import format_label_result
        doc_format = doc_path.suffix.lower().replace(".", "")
        contest_output = format_label_result(
            result,
            doc_path=doc_path,
            total_pages=0,  # 暂时无法从 docx 快速获取页数
            template_appendix_found=False,
            template_compliant=None,
        )
        write_audit_json(contest_output, out_path)
        log.info("赛题格式结果已写入 %s", out_path)
        print(f"  output: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
