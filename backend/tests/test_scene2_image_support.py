from pathlib import Path

from src.agents.scene2.image_agents import I1EvacuationRouteAgent
from src.agents.scene2.image_classifier import classify_images
from src.llm.mock_provider import MockProvider


def test_classify_images_prefers_filename_keywords_over_default_order() -> None:
    classified = classify_images(
        [
            "docs/现场疏散路线图.png",
            "docs/现场总平面图.jpg",
            "docs/附件/审批签字页-01.jpeg",
        ]
    )

    assert classified["I1_evacuation_route"] == ["docs/现场疏散路线图.png"]
    assert classified["I6_approval_page"] == ["docs/附件/审批签字页-01.jpeg"]
    assert classified["I4_entry_route"] == ["docs/现场总平面图.jpg"]


def test_classify_images_uses_predictable_default_order_without_provider() -> None:
    classified = classify_images(
        [
            "docs/image-001.png",
            "docs/image-002.png",
            "docs/image-003.png",
        ],
        provider=None,
        vision_model="",
    )

    assert classified == {
        "I1_evacuation_route": ["docs/image-001.png"],
        "I4_entry_route": ["docs/image-002.png"],
        "I2_assembly_point": ["docs/image-003.png"],
    }


def test_classify_images_ignores_vision_when_model_missing() -> None:
    provider = MockProvider(vision_handler=lambda path, prompt, model: "I5_hca_aerial")

    classified = classify_images(["docs/unknown.png"], provider=provider, vision_model="")

    assert classified == {"I1_evacuation_route": ["docs/unknown.png"]}
    assert provider.vision_calls == []


def test_i1_image_agent_returns_findings_from_mock_provider() -> None:
    provider = MockProvider(
        vision_handler=lambda path, prompt, model: (
            '{"疏散路线清晰可辨": true, '
            '"起点终点与方向标识完整": "缺失终点标识", '
            '"关键风险点和障碍物已标注": false, '
            '"confidence": 0.84}'
        )
    )
    agent = I1EvacuationRouteAgent(provider, "mock-vision")

    result = agent.run([str(Path("docs") / "scene2-route.png")])

    assert result.dimension == "I1_evacuation_route"
    assert result.verdict == "partial"
    assert result.score == 8
    assert result.confidence == 84
    assert result.need_human_review is False
    assert len(result.findings) == 2
    assert {finding.severity for finding in result.findings} == {"high", "medium"}
    assert any("缺失终点标识" in finding.description for finding in result.findings)
    assert any("scene2-route.png" in finding.evidence for finding in result.findings)
    assert provider.vision_calls[0]["model"] == "mock-vision"
