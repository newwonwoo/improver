"""LLM 진단 엔진 테스트 (MockClient 사용)."""
from engine.llm import MockClient, generate_recommendations, judge_findings
from engine.parser import parse_law
from engine.rules import F04Deemed, F05Discretion, E05Sanction
from engine.scorer import compute


def _build_result(text: str, name: str = "테스트법", category: str = "일반"):
    law = parse_law(text, name=name, law_category=category)
    findings = (
        F04Deemed().scan(law) + F05Discretion().scan(law) + E05Sanction().scan(law)
    )
    return compute(law, findings)


def test_llm_judge_downgrades_severity_on_false_positive():
    text = "제10조(동의의제) 신청인이 30일 이내 회신하지 아니하면 동의한 것으로 본다."
    result = _build_result(text)
    assert any(f.pattern_id == "F-04" for f in result.findings)

    mock = MockClient(
        default={
            "is_deemed_consent": False,
            "reasoning": "법적 지위 의제로 판단됨.",
            "deemed_type": "해당없음",
            "severity": "양호",
            "severity_basis": "오탐",
        }
    )
    judge_findings(result, client=mock)
    f = next(f for f in result.findings if f.pattern_id == "F-04")
    assert f.is_false_positive is True
    assert f.severity == "양호"


def test_llm_judge_adjusts_severity_within_one_step():
    text = "제10조(재량) 국토교통부장관은 필요하다고 인정하는 경우에는 조치를 할 수 있다."
    result = _build_result(text)
    assert any(f.pattern_id == "F-05" for f in result.findings)

    mock = MockClient(
        default={
            "is_arbitrary_discretion": True,
            "reasoning": "포괄재량 + 통제 장치 일부 존재.",
            "discretion_type": "포괄재량",
            "subject": "행정청",
            "impact_level": "재산권",
            "control_mechanisms": ["보고의무"],
            "severity": "경고",
            "severity_basis": "통제 장치 일부 존재로 한 단계 하향.",
        }
    )
    judge_findings(result, client=mock)
    f = next(f for f in result.findings if f.pattern_id == "F-05")
    assert f.severity == "경고"
    assert "LLM:" in f.summary


def test_llm_judge_two_step_change_flags_review_only():
    text = "제10조(재량) 국토교통부장관은 필요하다고 인정하는 경우에는 사업자의 허가를 취소할 수 있다."
    result = _build_result(text)

    mock = MockClient(
        default={
            "is_arbitrary_discretion": True,
            "reasoning": "x",
            "severity": "개선",  # 심각 → 개선 = 3단계 변화 → 보류
            "severity_basis": "x",
        }
    )
    judge_findings(result, client=mock)
    f = next(f for f in result.findings if f.pattern_id == "F-05")
    assert f.severity == "심각"  # 원래 등급 유지
    assert f.recommendation.get("human_review_needed") is True


def test_recommendations_layer3_attaches_contextual():
    text = "제10조(재량) 국토교통부장관은 필요하다고 인정하면 조치할 수 있다."
    result = _build_result(text)
    # 룰 단계 권고 부착 (Layer 1)
    result.findings[0].recommendation = {"template": "표준 권고안", "layer": 1}

    mock = MockClient(
        default={
            "adjusted_severity": "심각",
            "severity_changed": False,
            "recommendation": "제10조 후단에 발동 요건 5종을 호로 열거하라.",
            "action_type": "즉시개정",
            "reference_note": "법제처 입안길잡이 §32.",
        }
    )
    generate_recommendations(result, client=mock)
    f = result.findings[0]
    assert f.recommendation["layer"] == 3
    assert "발동 요건" in f.recommendation["contextual"]


def test_mock_client_records_calls():
    mock = MockClient(default={
        "is_deemed_consent": True, "severity": "심각", "reasoning": "x", "severity_basis": "y",
    })
    text = "제10조 통지하여야 한다. 30일 이내 회신하지 아니하면 동의한 것으로 본다."
    result = _build_result(text)
    judge_findings(result, client=mock)
    assert len(mock.calls) >= 1
