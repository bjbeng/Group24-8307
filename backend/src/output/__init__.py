"""输出层：JSON / MD / 带批注 DOCX。"""

from .json_writer import write_audit_json
from .annotator import write_outputs, generate_markdown_report, annotate_docx

__all__ = ["write_audit_json", "write_outputs", "generate_markdown_report", "annotate_docx"]
