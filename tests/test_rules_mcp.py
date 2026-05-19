"""L-02, L-03, S-02 단계2 룰 테스트."""
from engine.mcp import LawIndex
from engine.parser import parse_law
from engine.rules import L02CrossRef, L03BrokenRef, S02Delegation


def _law(text: str, name: str = "테스트법", category: str = "일반"):
    return parse_law(text, name=name, law_category=category)


def _custom_index() -> LawIndex:
    return LawIndex(
        laws=[
            {
                "name": "주택도시기금법",
                "short_names": [],
                "article_count": 43,
                "article_numbers": ["10", "12"],
                "has_enforcement_decree": True,
                "enforcement_decree_name": "주택도시기금법 시행령",
            },
            {
                "name": "주택도시기금법 시행령",
                "short_names": [],
                "article_numbers": ["10"],
            },
        ],
        repealed={
            "폐지": [{"name": "구법", "repealed_date": "2010-01-01", "successor": "신법"}],
            "제명변경": [{"old_name": "옛이름법", "new_name": "새이름법", "date": "2020-01-01"}],
        },
    )


def test_l02_cross_ref_warning_on_five_laws():
    text = (
        "제9조(참조) 이 법은 「민법」 제1조, 「상법」 제2조, 「소득세법」 제3조, "
        "「국유재산법」 제4조, 「자본시장과 금융투자업에 관한 법률」 제5조에 따른다."
    )
    findings = L02CrossRef().scan(_law(text))
    assert findings and findings[0].severity == "주의"


def test_l03_broken_ref_repealed_critical():
    text = "제5조(인용) 이 조는 「구법」 제1조에 따른다."
    rule = L03BrokenRef(index=_custom_index())
    findings = rule.scan(_law(text))
    assert findings and findings[0].severity == "심각"
    assert "폐지" in findings[0].summary


def test_l03_broken_ref_renamed_caution():
    text = "제5조(인용) 이 조는 「옛이름법」 제1조에 따른다."
    rule = L03BrokenRef(index=_custom_index())
    findings = rule.scan(_law(text))
    assert findings and findings[0].severity == "주의"


def test_l03_broken_ref_missing_article_warning():
    text = "제5조(인용) 이 조는 「주택도시기금법」 제99조에 따른다."
    rule = L03BrokenRef(index=_custom_index())
    findings = rule.scan(_law(text))
    assert findings and findings[0].severity == "경고"


def test_l03_existing_ref_no_finding():
    text = "제5조(인용) 이 조는 「주택도시기금법」 제10조에 따른다."
    rule = L03BrokenRef(index=_custom_index())
    findings = rule.scan(_law(text))
    assert findings == []


def test_s02_phase2_partial_coverage_warning():
    # 포괄위임 catch-all → 경고 (그 밖에 필요한 사항은 대통령령으로 정한다)
    text = "제12조(위임) 그 밖에 필요한 사항은 대통령령으로 정한다."
    rule = S02Delegation(index=_custom_index())
    law = _law(text, name="주택도시기금법", category="공공기관법")
    findings = rule.scan(law)
    severities = {f.severity for f in findings}
    assert "경고" in severities or "주의" in severities
