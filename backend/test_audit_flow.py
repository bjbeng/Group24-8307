"""验证 audit 流程能跑通，ChunkRef 坐标正确。

数据流：
  parse_with_mineru() → ParsedBlock → chunk_parsed_blocks() → Chunk
  → Chunk.to_row() dict → collect_chunks() → ChunkRef (含 bbox/page_start/section_path)
  → Agent.run(rows)
"""
import sys
sys.path.insert(0, "src")

from src.parse.mineru_parser import parse_with_mineru, ParsedBlock
from src.chunk.text_chunk import chunk_parsed_blocks
from src.chunk.models import Chunk
from src.agents.llm_audit_utils import collect_chunks, ChunkRef


def test_chunkref_fieldPropagation(doc_path: str) -> dict[str, object]:
    """完整数据流的端到端验证。"""
    results: dict[str, object] = {}

    # ── 1. MinerU parse ────────────────────────────────────────────────
    print("\n=== 1. parse_with_mineru ===")
    result = parse_with_mineru(doc_path, language="ch")
    # result 是 (blocks, doc_summary, toc) 三元组
    if isinstance(result, tuple) and len(result) == 3:
        blocks, doc_summary, toc = result
    else:
        # 旧版实现可能只返回 blocks（防御性处理）
        blocks = result
        doc_summary, toc = None, None
    print(f"  ParsedBlock count: {len(blocks)}")
    print(f"  doc_summary: {str(doc_summary)[:80] if doc_summary else 'N/A'}...")
    print(f"  TOC entries: {len(toc) if toc else 0}")
    results["parsed_block_count"] = len(blocks)

    if not blocks:
        print("  [WARN] No blocks parsed — is MinerU server running?")
        return results

    # 验证 ParsedBlock 有坐标
    sample_pb = next((b for b in blocks if b.block_type == "text"), blocks[0])
    print(f"  Sample ParsedBlock:")
    print(f"    block_type={sample_pb.block_type}")
    print(f"    page_number={sample_pb.page_number}  (1-based)")
    print(f"    bbox={sample_pb.bbox}")
    results["sample_parsedblock"] = {
        "block_type": sample_pb.block_type,
        "page_number": sample_pb.page_number,
        "bbox": sample_pb.bbox,
    }

    # ── 2. chunk_parsed_blocks → Chunk list ────────────────────────────
    print("\n=== 2. chunk_parsed_blocks ===")
    doc_id = "test_doc"
    chunks = chunk_parsed_blocks(blocks, doc_id=doc_id, max_tokens=800)
    print(f"  Chunk count: {len(chunks)}")
    results["chunk_count"] = len(chunks)

    if not chunks:
        print("  [ERROR] No chunks produced")
        return results

    # 检查坐标字段
    sample_chunk = chunks[0]
    print(f"  First chunk:")
    print(f"    chunk_id={sample_chunk.chunk_id}")
    print(f"    chunk_type={sample_chunk.chunk_type}")
    print(f"    section_path={sample_chunk.section_path}")
    print(f"    page_start={sample_chunk.page_start}")
    print(f"    page_end={sample_chunk.page_end}")
    print(f"    bbox={sample_chunk.bbox}")
    results["first_chunk_has_bbox"] = sample_chunk.bbox is not None
    results["first_chunk_page_start"] = sample_chunk.page_start
    results["first_chunk_section_path"] = sample_chunk.section_path

    # 统计有 bbox 的 chunk 比例
    has_bbox = sum(1 for c in chunks if c.bbox is not None)
    print(f"  Chunks with bbox: {has_bbox}/{len(chunks)} ({100*has_bbox/len(chunks):.0f}%)")

    # ── 3. Chunk.to_row() → dict ───────────────────────────────────────
    print("\n=== 3. Chunk.to_row() ===")
    rows = [c.to_row() for c in chunks]
    sample_row = rows[0]
    print(f"  row keys: {list(sample_row.keys())}")
    print(f"  row bbox value: {sample_row['bbox']!r}  (type={type(sample_row['bbox']).__name__})")
    results["row_bbox_type"] = type(sample_row["bbox"]).__name__
    results["row_has_bbox_key"] = "bbox" in sample_row

    # ── 4. collect_chunks → ChunkRef list ──────────────────────────────
    print("\n=== 4. collect_chunks ===")
    refs = collect_chunks(
        rows,
        keywords=None,
        chunk_types=("TEXT", "HEADING"),
        max_chunks=5,
        seed=42,
    )
    print(f"  ChunkRef count: {len(refs)}")
    results["chunkref_count"] = len(refs)

    for r in refs:
        print(f"  [{r.chunk_id}]")
        print(f"    section_path={r.section_path!r}")
        print(f"    page_start={r.page_start}  page_end={r.page_end}")
        print(f"    bbox={r.bbox!r}  (type={type(r.bbox).__name__})")
        print(f"    chunk_type={r.chunk_type}")

    # ── 5. 检查数据完整性 ──────────────────────────────────────────────
    print("\n=== 5. 数据完整性检查 ===")
    issues: list[str] = []

    # 5a. ParsedBlock.bbox → Chunk.bbox
    for c in chunks:
        if c.bbox is not None:
            if not isinstance(c.bbox, list) or len(c.bbox) != 4:
                issues.append(f"Chunk {c.chunk_id}: bbox 不是 [x0,y0,x1,y1] 格式: {c.bbox!r}")
            elif not all(isinstance(v, (int, float)) for v in c.bbox):
                issues.append(f"Chunk {c.chunk_id}: bbox 包含非数值: {c.bbox!r}")

    # 5b. to_row → collect_chunks 链路
    for r in refs:
        if r.bbox is None:
            issues.append(f"ChunkRef {r.chunk_id}: bbox 为 None（来源 chunk 可能有 bbox）")
        elif isinstance(r.bbox, str):
            issues.append(f"ChunkRef {r.chunk_id}: bbox 是字符串而非 list: {r.bbox!r}")
        elif not isinstance(r.bbox, list):
            issues.append(f"ChunkRef {r.chunk_id}: bbox 类型异常: {type(r.bbox).__name__}")
        if r.page_start <= 0:
            issues.append(f"ChunkRef {r.chunk_id}: page_start 异常: {r.page_start}")

    results["issues"] = issues
    if issues:
        print("  [ISSUE] 发现数据流问题:")
        for iss in issues:
            print(f"    - {iss}")
    else:
        print("  [OK] 所有检查通过")

    return results


if __name__ == "__main__":
    import os
    # 优先用项目内的测试文档
    candidates = [
        "data/tmp/AS_/AS作业区作业指导书.docx",
        "data/tmp/AS_/AS作业区作业指导书.pdf",
    ]
    doc = None
    for c in candidates:
        full = os.path.join(os.path.dirname(__file__), c)
        if os.path.exists(full):
            doc = full
            break

    if len(sys.argv) > 1:
        doc = sys.argv[1]

    if doc and os.path.exists(doc):
        print(f"Using document: {doc}")
        results = test_chunkref_fieldPropagation(doc)
        print("\n=== 最终结果 ===")
        print(f"  parsed_blocks: {results.get('parsed_block_count', 0)}")
        print(f"  chunks: {results.get('chunk_count', 0)}")
        print(f"  ChunkRef: {results.get('chunkref_count', 0)}")
        print(f"  first_chunk_has_bbox: {results.get('first_chunk_has_bbox')}")
        print(f"  row_bbox_type: {results.get('row_bbox_type')}")
        print(f"  issues: {results.get('issues', [])}")
    else:
        # 无文档时只验证 import + 基本结构
        print("No document found — verifying structure only")
        print("Import check: OK (already verified above)")

        # 验证 Chunk 字段
        c = Chunk(
            chunk_id="test__ROOT__text__001",
            doc_id="test",
            chunk_type=ChunkType.TEXT,
            section_path="1.1",
            title="Test",
            content="测试内容",
            paragraph_index=0,
            anchor_text="测试",
            page_start=1,
            page_end=1,
            bbox=[100.0, 200.0, 300.0, 400.0],
        )
        row = c.to_row()
        print(f"\nChunk.to_row() bbox field: {row['bbox']!r}")

        from src.chunk.models import ChunkType

        # 验证 collect_chunks 能处理 to_row 输出
        rows = [row]
        refs = collect_chunks(rows, keywords=None, chunk_types=("TEXT",), max_chunks=3, seed=42)
        print(f"collect_chunks from to_row: {len(refs)} refs")
        if refs:
            r = refs[0]
            print(f"  bbox={r.bbox!r}  type={type(r.bbox).__name__}")
            print(f"  page_start={r.page_start}")
            print(f"  section_path={r.section_path!r}")
            if isinstance(r.bbox, list) and len(r.bbox) == 4:
                print("  [OK] bbox 是正确的 4元素 list")
            else:
                print(f"  [ISSUE] bbox 格式异常: {r.bbox!r}")