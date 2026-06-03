from engine.schema import Article, Finding, Law
from engine.scorer import compute
from engine.severity import grade_of_law, grade_of_article, score_of


def _make_finding(pattern_id: str, category: str, severity: str,
                  article_id: str = "art_10", article_number: str = "제10조") -> Finding:
    return Finding(
        finding_id=f"{pattern_id}-001",
        pattern_id=pattern_id,
        pattern_name=pattern_id,
        category=category,
        article_id=article_id,
        article_number=article_number,
        matched_text="x",
        severity=severity,
        severity_score=score_of(severity),
        summary="x",
    )


def test_article_complexity_bonus_design_example():
    """핵심 설계서 §1.4 예시: 제10조 삽입조(경고7) + 위임(주의4) + 모호(심각10) → 13.0."""
    law = Law(law_id="x", name="x",
              articles=[Article(article_id="art_10", number="제10조", number_raw="10")])
    findings = [
        _make_finding("S-01", "구조", "경고"),
        _make_finding("S-02", "구조", "주의"),
        _make_finding("S-03", "구조", "심각"),
    ]
    result = compute(law, findings)
    assert result.article_scores[0].score == 13.0
    assert result.article_scores[0].grade == "Critical"


def test_complexity_bonus_capped_at_six():
    law = Law(law_id="x", name="x",
              articles=[Article(article_id="art_10", number="제10조", number_raw="10")])
    findings = [
        _make_finding(pid, "구조", "심각")
        for pid in ("S-01", "S-02", "S-03", "F-01", "F-02", "F-03", "L-01")
    ]
    result = compute(law, findings)
    # max=10, bonus=min((7-1)*1.5, 6.0)=6.0 → 16.0
    assert result.article_scores[0].score == 16.0


def test_law_grade_thresholds():
    assert grade_of_law(0.0) == "A"
    assert grade_of_law(14.9) == "A"
    assert grade_of_law(15.0) == "B"
    assert grade_of_law(29.9) == "B"
    assert grade_of_law(30.0) == "C"
    assert grade_of_law(50.0) == "D"
    assert grade_of_law(75.0) == "F"


def test_article_grade_thresholds():
    assert grade_of_article(10.0) == "Critical"
    assert grade_of_article(7.0) == "Warning"
    assert grade_of_article(4.0) == "Caution"
    assert grade_of_article(2.0) == "Minor"
    assert grade_of_article(0.0) == "Clean"


def test_category_crd_and_weight():
    """구조 카테고리에 finding 1건(심각=10)이고 조문수 10개면 CRD=100, 가중치 1.0."""
    law = Law(law_id="x", name="x", law_category="일반",
              articles=[Article(article_id=f"art_{i}", number=f"제{i}조", number_raw=str(i))
                        for i in range(1, 11)])
    findings = [_make_finding("S-03", "구조", "심각")]
    result = compute(law, findings)
    assert result.category_scores["구조"].crd == 100.0
    assert result.category_scores["구조"].weight == 1.0
