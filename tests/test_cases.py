"""Layer 2 사례 + 기관 매핑 테스트."""
from engine import cases
from engine.schema import AnalysisResult, Article, Finding, Law


def _result(pattern_id: str, sub_check_id: str | None = None) -> AnalysisResult:
    art = Article(article_id="art_22", number="제22조", number_raw="22")
    law = Law(law_id="x", name="주택도시기금법", law_category="공공기관법", articles=[art])
    rec = {"sub_check_id": sub_check_id} if sub_check_id else {}
    f = Finding(
        finding_id="x-001",
        pattern_id=pattern_id,
        pattern_name=pattern_id,
        category="거버넌스",
        article_id="art_22",
        article_number="제22조",
        matched_text="x",
        severity="심각",
        severity_score=10,
        summary="x",
        recommendation=rec,
    )
    return AnalysisResult(
        law=law, findings=[f], article_scores=[], category_scores={},
        law_score=0.0, law_grade="A",
    )


def test_attach_matches_case_by_pattern_id():
    result = cases.attach(_result("G-04"))
    rec = result.findings[0].recommendation
    assert rec.get("matched_cases")
    assert any(c["case_id"] == "BAI-2024-001" for c in rec["matched_cases"])


def test_attach_uses_sub_check_for_agency_lookup():
    result = cases.attach(_result("G-04", sub_check_id="G-04-b"))
    rec = result.findings[0].recommendation
    assert "감사원" in rec.get("related_agencies", [])
    assert "금감원" in rec.get("related_agencies", [])


def test_attach_reference_note_from_first_case():
    result = cases.attach(_result("G-04"))
    rec = result.findings[0].recommendation
    assert "감사원" in (rec.get("reference_note") or "")


def test_attach_returns_empty_for_unknown_pattern():
    result = cases.attach(_result("Z-99"))
    rec = result.findings[0].recommendation
    assert not rec.get("matched_cases")
    assert not rec.get("related_agencies")


def test_attach_skips_false_positives():
    res = _result("G-04")
    res.findings[0].is_false_positive = True
    cases.attach(res)
    assert "matched_cases" not in res.findings[0].recommendation
