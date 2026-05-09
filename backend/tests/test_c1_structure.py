from src.agents.scene1.c1_structure import check_appendix_has_content, extract_structure


def test_extract_structure_reads_heading_title_from_heading_chunks() -> None:
    chunks = [
        {
            "chunk_id": "doc__1__heading__001",
            "chunk_type": "heading",
            "title": "1 岗位条件",
            "content": "",
            "section_path": "1",
            "heading_level": 1,
            "paragraph_index": 3,
        },
        {
            "chunk_id": "doc__2__heading__001",
            "chunk_type": "heading",
            "title": "2 岗位职责",
            "content": "",
            "section_path": "2",
            "heading_level": 1,
            "paragraph_index": 8,
        },
    ]

    facts = extract_structure(chunks)

    assert [heading["title"] for heading in facts.headings] == ["1 岗位条件", "2 岗位职责"]
    assert [heading["level"] for heading in facts.headings] == [1, 1]
    assert [heading["section_path"] for heading in facts.headings] == ["1", "2"]


def test_extract_structure_only_treats_heading_chunks_as_appendix_sections() -> None:
    chunks = [
        {
            "chunk_id": "doc__9__heading__001",
            "chunk_type": "heading",
            "title": "9 附件",
            "content": "9 附件",
            "section_path": "9",
            "paragraph_index": 0,
        },
        {
            "chunk_id": "doc__9__text__001",
            "chunk_type": "text",
            "title": "9 附件",
            "content": "这是附件说明内容，长度足够超过二十个字符。",
            "section_path": "9",
            "paragraph_index": 1,
        },
    ]

    facts = extract_structure(chunks)

    assert len(facts.appendix_sections) == 1
    assert facts.appendix_sections[0].chunk_id == "doc__9__heading__001"
    assert facts.appendix_sections[0].has_content is True
    assert check_appendix_has_content(facts) == []
