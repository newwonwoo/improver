"""Phase 2 요구사항 추출기 + 비교 단위 테스트."""
from engine.phase2 import RequirementType, ViolationKind, compare, extract_requirements
from engine.schema import AnalysisResult, Article, Finding, Law


def _result_with_findings(*subchecks: tuple[str, str]) -> AnalysisResult:
    art = Article(article_id="art_22", number="제22조", number_raw="22")
    law = Law(law_id="x", name="주택도시기금법", articles=[art])
    findings = []
    for i, (sub, pat) in enumerate(subchecks):
        findings.append(Finding(
            finding_id=f"f-{i}",
            pattern_id=pat,
            pattern_name=pat,
            category="거버넌스",
            article_id="art_22",
            article_number="제22조",
            matched_text="x",
            severity="심각",
            severity_score=10,
            summary="x",
            recommendation={"sub_check_id": sub},
        ))
    return AnalysisResult(law=law, findings=findings, article_scores=[],
                          category_scores={}, law_score=0.0, law_grade="A")


def test_extract_requirements_g04_five_elements():
    result = _result_with_findings(
        ("G-04-a", "G-04"), ("G-04-b", "G-04"), ("G-04-e", "G-04"),
    )
    reqs = extract_requirements(result)
    types = {r.sub_check_id: r.type for r in reqs}
    assert types["G-04-a"] == RequirementType.REQUIRE
    assert types["G-04-b"] == RequirementType.REQUIRE
    assert types["G-04-e"] == RequirementType.REQUIRE


def test_extract_requirements_skips_unmapped_subchecks():
    result = _result_with_findings(("Z-99-z", "Z"))
    assert extract_requirements(result) == []


def test_compare_detects_missing_requirement():
    result = _result_with_findings(("G-04-b", "G-04"))
    reqs = extract_requirements(result)
    violations = compare(reqs, internal_text="우리 회사 규정은 매년 회의를 한다.")
    assert violations and violations[0].kind == ViolationKind.MISSING


def test_compare_detects_excess_forbid():
    """F-02-a 전면면책 forbid — 사내규정에 '일체의 책임' 포함되면 초과."""
    result = _result_with_findings(("F-02-a", "F-02"))
    # F-02-a는 거버넌스가 아니라 공정성이지만 category로 분류 영향 없음
    result.findings[0].category = "공정성"
    reqs = extract_requirements(result)
    violations = compare(reqs, internal_text="회사는 일체의 책임을 지지 않는다.")
    assert violations and violations[0].kind == ViolationKind.EXCESS


def test_compare_passes_when_internal_text_satisfies():
    result = _result_with_findings(("G-04-b", "G-04"))
    reqs = extract_requirements(result)
    violations = compare(reqs, internal_text="제3조(위험관리) 회사는 위험평가를 매년 실시한다.")
    assert violations == []
