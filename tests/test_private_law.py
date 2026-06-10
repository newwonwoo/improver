"""사법(私法) 확장 착수 테스트 — P-DIGITAL 정밀 필터 + taxonomy 정직성."""
from pathlib import Path

from engine.parser import parse_law
from engine.private_law import (
    detect_private_law_defects,
    active_types,
    scaffold_types,
    PRIVATE_LAW_TAXONOMY,
)


def _law(text):
    return parse_law(text, name="사법테스트")


def test_taxonomy_honest_split():
    # 착수: active 1종(검증), scaffold 4종(SME 대기) — 정직 분리
    assert active_types() == ["P-DIGITAL"]
    assert set(scaffold_types()) == {"P-ARCHAIC", "P-DISCRIM", "P-CITATION",
                                     "P-OBSOLETE-UNIT"}
    for t in PRIVATE_LAW_TAXONOMY.values():
        assert t.fp_risk_note            # 모든 유형이 FP 위험을 명시(정직)


def test_digital_unfit_fires_on_mandatory_seal_without_alternative():
    law = _law("제40조(정관) 설립자는 정관을 작성하여 기명날인하여야 한다.")
    fs = detect_private_law_defects(law)
    assert len(fs) == 1
    assert fs[0].code == "P-DIGITAL"
    assert "기명날인" in fs[0].matched_text
    assert "전자서명" in fs[0].recommendation       # 디지털 대체 권고


def test_already_modernized_is_filtered_precision():
    # '기명날인하거나 서명' = 이미 서명 대체 허용 → 정비 불요(FP 제외)
    law = _law("제86조(조합계약) 총조합원이 기명날인하거나 서명하여야 한다.")
    assert detect_private_law_defects(law) == []

    law2 = _law("제30조 작성자가 기명날인 또는 서명하여야 한다.")
    assert detect_private_law_defects(law2) == []


def test_optional_seal_not_fired():
    # 강제(하여야)가 아닌 임의 → 미발화
    law = _law("제100조 당사자는 계약서에 날인할 수 있다.")
    assert detect_private_law_defects(law) == []


def test_private_law_is_separate_from_admin_engine():
    """사법 탐지는 행정규제법 run_all 과 분리 — finding 스키마도 별개."""
    from engine.private_law.detect import PrivateLawFinding
    f = PrivateLawFinding(code="P-DIGITAL", article_number="제1조",
                          article_title="x", matched_text="날인하여야 한다",
                          rationale="r", recommendation="rec")
    assert not hasattr(f, "pattern_id")     # 행정 Finding 과 다른 스키마
    assert f.code.startswith("P-")
