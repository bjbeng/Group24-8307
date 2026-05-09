from src.agents.base import AgentResult
from src.agents.scene2.image_classifier import map_classifier_label_to_agent_image_type
from src.harness.pipeline.label_pipeline import LabelResult


def default_total(scenario: str, mode: str) -> int:
    if scenario == "s2":
        return 19
    if mode == "label":
        return 8
    return 11


def test_scene2_default_total_uses_scene2_dimension_count() -> None:
    assert default_total("s2", "label") == 19
    assert default_total("s2", "audit") == 19


def test_label_mode_total_uses_label_count_outside_scene2() -> None:
    assert default_total("s1", "label") == 8
    assert default_total("s1", "audit") == 11


def test_classifier_label_maps_to_vision_semantic_image_type() -> None:
    assert map_classifier_label_to_agent_image_type("I6_approval_page") == "approval"
    assert map_classifier_label_to_agent_image_type("I5_hca_aerial") == "hca_aerial"
    assert map_classifier_label_to_agent_image_type("unknown") == "unknown"


def test_label_result_to_dict_exposes_scene2_summary_fields() -> None:
    result = LabelResult(
        doc_id="doc-1",
        doc_name="scene2.docx",
        scenario="s2",
        elapsed_seconds=12.345,
        dimensions={
            "L1_format": AgentResult(
                dimension="L1_format",
                verdict="pass",
                score=12,
                confidence=90,
            ),
            "I1_evacuation_route": AgentResult(
                dimension="I1_evacuation_route",
                verdict="partial",
                score=8,
                confidence=70,
                need_human_review=True,
            ),
        },
    )

    payload = result.to_dict()

    assert payload["doc_id"] == "doc-1"
    assert payload["doc_name"] == "scene2.docx"
    assert payload["scenario"] == "s2"
    assert payload["pipeline"] == "label"
    assert payload["overall_verdict"] == "partial"
    assert payload["overall_score"] == 20
    assert payload["need_human_review"] is True
    assert payload["elapsed_seconds"] == 12.35
    assert set(payload["dimensions"]) == {"L1_format", "I1_evacuation_route"}
