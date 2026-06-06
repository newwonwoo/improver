"""S6 개선안 품질 채점기 테스트."""
from engine.recommend_quality import score_recommendation


def test_high_quality_contextual():
    # 조문 지목 + 인용 + 실행동사 → 고품질, 플래그 없음
    s = score_recommendation(
        "제3조의 '필요한 사항'을 '피해자 인정 절차·제출서류·심사기준'으로 한정 열거하라",
        article_ref="제3조",
    )
    assert s["actionability"] == 1.0
    assert s["specificity"] >= 0.75
    assert not s["low_quality"]


def test_generic_boilerplate_low():
    s = score_recommendation("조치 불요.")
    assert s["low_quality"]


def test_empty_low():
    assert score_recommendation("")["low_quality"]


def test_mid_template():
    # 실행동사는 있으나 조문 지목·인용 없음(일반 템플릿)
    s = score_recommendation("위임 대상을 구체적 항목으로 한정.")
    assert s["actionability"] == 1.0
    assert s["specificity"] < 0.5
