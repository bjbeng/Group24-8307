from src.agents.scene1.e1_staffing import StaffingFacts, derive_verdict, evaluate_staffing
from src.agents.scene1.e2_emergency import E2EmergencyAgent
from src.llm import Message
from src.llm.mock_provider import MockProvider


def test_e1_engineer_rule_uses_pipeline_length() -> None:
    facts = StaffingFacts(
        pipeline_length_km=250.0,
        safety_engineers_actual=2,
        patrol_workers_actual=30,
    )

    rules, findings = evaluate_staffing(facts)

    engineer_rule = next(rule for rule in rules if rule["rule"] == "safety_engineer")
    assert engineer_rule["required"] == 3
    assert engineer_rule["passed"] is False
    assert any(f.rule_id == "E1_staffing.safety_engineer" for f in findings)


def test_e1_verdict_is_uncertain_without_pipeline_length() -> None:
    facts = StaffingFacts(total_employees=120, safety_engineers_actual=2, patrol_workers_actual=6)

    verdict, score, confidence = derive_verdict([], [], facts)

    assert verdict == "uncertain"
    assert score == 0
    assert confidence == 30


def test_e2_extracts_and_exposes_step_alignment() -> None:
    responses = iter(
        [
            '{"main_steps":["立即上报","关闭阀门"],"appendix_steps":["立即上报","关闭阀门"],"missing_side":"none","summary":"正文与处置卡步骤一致"}',
            '{"verdict":"pass","score":12,"confidence":88,"details":"流程与处置卡一致","findings":[],"extra":{"checked":"alignment"}}',
        ]
    )

    def handler(messages: list[Message], model: str) -> str:
        return next(responses)

    agent = E2EmergencyAgent(MockProvider(text_handler=handler), "mock-model")
    chunks = [
        {
            "chunk_id": "c1",
            "chunk_type": "TEXT",
            "content": "应急处置流程：发现泄漏后立即上报，关闭阀门，组织人员疏散。",
            "section_path": "3.1",
            "page_start": 2,
            "page_end": 2,
        },
        {
            "chunk_id": "c2",
            "chunk_type": "TEXT",
            "content": "附录C 现场处置卡：立即上报，关闭阀门，组织人员疏散。",
            "section_path": "附录C",
            "page_start": 8,
            "page_end": 8,
        },
    ]

    result = agent.run(chunks)

    assert result.verdict == "pass"
    assert result.extra["main_steps"] == ["立即上报", "关闭阀门"]
    assert result.extra["appendix_steps"] == ["立即上报", "关闭阀门"]
    assert result.extra["missing_side"] == "none"
    assert result.extra["step_alignment_summary"] == "正文与处置卡步骤一致"
