from pathlib import Path

from engine import cases, fpc, html_report, recommender, scorer
from engine.parser import parse_law
from engine.rules import run_all

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "synthetic_housing_fund.txt"


def _run():
    law = parse_law(FIXTURE.read_text(encoding="utf-8"),
                    name="주택도시기금법", law_category="공공기관법")
    findings = fpc.correct(law, run_all(law))
    result = scorer.compute(law, findings)
    result = recommender.apply(result)
    return cases.attach(result)


def test_html_report_contains_law_name_and_grade():
    html = html_report.render(_run())
    assert "「주택도시기금법」" in html
    assert "발견" in html
    assert "<html" in html and "</html>" in html


def test_html_report_includes_finding_sections():
    html = html_report.render(_run())
    for cat in ["구조", "공정성", "거버넌스", "효율성"]:
        assert cat in html


def test_html_report_renders_case_links():
    html = html_report.render(_run())
    # G-04는 케이스 매칭이 있어 외부 링크가 노출돼야
    assert "감사원" in html


def test_html_report_renders_checklist():
    html = html_report.render(_run())
    assert "사내규정 반영 체크리스트" in html
