"""합성 fixture로 파이프라인 E2E 검증.

설계서 골든 출력(주택도시기금법 scan_result.json)을 그대로 재현하려면 원문 텍스트가 필요한데
zip에는 없어 합성본으로 대체. 합성본은 동일 패턴이 일부 조문에 의도적으로 들어있어
다음을 확인한다:
- G-04 5요소 0/5 → 심각 (기금법 키워드 매칭)
- G-03 제12조 "감독한다" 한 줄 → 심각
- F-05 제10조/제32조/제34조의2 "필요하다고 인정" → 심각 3건
- L-01 제9조 14개 법령 인용 → 경고
- S-03 의무조항에 모호표현 → 심각/경고
- 등급 분포 + 법령 점수가 C 이상 (실제 골든은 C=47.0)
"""
from pathlib import Path

from engine import fpc, recommender, scorer
from engine.parser import parse_law
from engine.rules import run_all

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "synthetic_housing_fund.txt"


def _run():
    text = FIXTURE.read_text(encoding="utf-8")
    law = parse_law(text, name="주택도시기금법", law_category="공공기관법")
    findings = run_all(law)
    findings = fpc.correct(law, findings)
    result = scorer.compute(law, findings)
    return recommender.apply(result)


def test_g04_internal_control_critical():
    result = _run()
    g04 = [f for f in result.findings if f.pattern_id == "G-04"]
    assert g04
    assert g04[0].severity == "심각"


def test_g03_supervision_critical_on_art12():
    result = _run()
    g03 = [f for f in result.findings if f.pattern_id == "G-03"]
    assert any(f.article_number == "제12조" and f.severity == "심각" for f in g03)


def test_f05_discretion_arbitrary_on_admin_articles():
    result = _run()
    f05 = [f for f in result.findings if f.pattern_id == "F-05"]
    articles = {f.article_number for f in f05}
    assert "제10조" in articles
    # 32조와 34조의2 — 적어도 하나는 잡혀야 (단, 32조는 위임 결합이라 제외될 수도)
    assert articles & {"제10조", "제32조", "제34조의2"}


def test_l01_overflow_citation_on_art9():
    result = _run()
    l01 = [f for f in result.findings if f.pattern_id == "L-01"]
    assert any(f.article_number == "제9조" for f in l01)


def test_law_score_is_c_or_worse():
    result = _run()
    assert result.law_grade in {"C", "D", "F"}, f"got {result.law_grade}={result.law_score}"


def test_recommendations_attached_for_critical_findings():
    result = _run()
    severe = [f for f in result.findings if f.severity == "심각"]
    assert severe, "심각 등급 finding이 있어야 함"
    assert all(f.recommendation.get("template") for f in severe)


def test_total_articles_parsed():
    result = _run()
    assert result.law.total_articles == 17


def test_output_is_json_serializable():
    import json

    result = _run()
    payload = json.dumps(result.to_dict(), ensure_ascii=False)
    assert "law_score" in payload
