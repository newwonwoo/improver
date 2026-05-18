from engine import cross_pattern
from engine.schema import AnalysisResult, Article, Finding, Law


def _finding(pattern: str, category: str, severity: str = "심각",
             article_id: str = "art_10", article_number: str = "제10조") -> Finding:
    return Finding(
        finding_id=f"{pattern}-001",
        pattern_id=pattern,
        pattern_name=pattern,
        category=category,
        article_id=article_id,
        article_number=article_number,
        matched_text="x",
        severity=severity,
        severity_score=10 if severity == "심각" else 7,
        summary="x",
    )


def _result(findings: list[Finding]) -> AnalysisResult:
    art = Article(article_id="art_10", number="제10조", number_raw="10")
    law = Law(law_id="x", name="x", articles=[art])
    return AnalysisResult(law=law, findings=findings, article_scores=[],
                          category_scores={}, law_score=0.0, law_grade="A")


def test_two_patterns_attach_meta_only_no_extra():
    res = _result([_finding("S-03", "구조"), _finding("F-01", "공정성")])
    cross_pattern.annotate(res)
    # 2패턴은 메타만 부착, X-CROSS finding 미생성
    extras = [f for f in res.findings if f.pattern_id.startswith("X-")]
    assert extras == []
    assert all(
        f.recommendation.get("cross_pattern_count") == 2
        for f in res.findings if not f.pattern_id.startswith("X-")
    )


def test_three_patterns_emit_redesign_warning():
    res = _result([
        _finding("S-03", "구조"),
        _finding("F-01", "공정성"),
        _finding("G-04", "거버넌스"),
    ])
    cross_pattern.annotate(res)
    extras = [f for f in res.findings if f.pattern_id == "X-CROSS"]
    assert len(extras) == 1
    assert "조문 재설계" in extras[0].summary or "조문 재설계" in extras[0].recommendation["template"]


def test_four_patterns_emit_restructure_warning():
    res = _result([
        _finding(p, "구조") for p in ("S-01", "S-03", "F-01", "G-04")
    ])
    cross_pattern.annotate(res)
    extras = [f for f in res.findings if f.pattern_id == "X-CROSS"]
    assert extras and "분리 입법" in extras[0].recommendation["template"]


def test_law_wide_pattern_repetition_warning():
    findings = [
        _finding("S-03", "구조", article_id=f"art_{i}", article_number=f"제{i}조")
        for i in range(1, 7)
    ]
    res = _result(findings)
    cross_pattern.annotate(res)
    extras = [f for f in res.findings if f.pattern_id == "X-PATTERN"]
    assert extras and "법령 차원" in extras[0].recommendation["template"]
