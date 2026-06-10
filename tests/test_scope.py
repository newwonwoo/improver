"""적용범위 신뢰도 가드레일 테스트 — 팀장 민법 probe 대응."""
from pathlib import Path

from engine.parser import parse_law
from engine.scope import scope_confidence, delegation_ratio


def _load(name):
    p = Path(f"data/laws/raw/{name}/법률.md")
    if not p.exists():
        return None
    t = p.read_text(encoding="utf-8", errors="replace")
    if t.lstrip().startswith("---"):
        t = t.split("---", 2)[2]
    return parse_law(t, name=name)


def test_admin_law_in_scope():
    law = _load("119구조ㆍ구급에관한법률")
    if law is None:
        return
    sc = scope_confidence(law)
    assert sc["confidence"] == "in_scope"
    assert sc["delegation_ratio"] >= 0.2
    assert sc["advisory"] == ""


def test_civil_code_out_of_scope_with_advisory():
    law = _load("민법")
    if law is None:
        return
    sc = scope_confidence(law)
    assert sc["confidence"] == "out_of_scope"
    assert "행정규제법" in sc["advisory"]
    assert "결함 없음" in sc["advisory"]        # '적은 발화=깨끗'으로 오인 방지 명시


def test_criminal_code_out_of_scope():
    law = _load("형법")
    if law is None:
        return
    sc = scope_confidence(law)
    assert sc["confidence"] == "out_of_scope"


def test_scope_is_metadata_only_no_finding_fields():
    """게이밍0: 신뢰도는 메타데이터 — 결함/심각도 필드를 만들지 않는다."""
    law = _load("민법") or _load("119구조ㆍ구급에관한법률")
    if law is None:
        return
    sc = scope_confidence(law, finding_count=6)
    assert "severity" not in sc and "findings" not in sc
    assert set(sc) >= {"confidence", "delegation_ratio", "reason", "advisory"}


def test_delegation_ratio_bounds():
    law = _load("민법")
    if law is None:
        return
    dr = delegation_ratio(law)
    assert 0.0 <= dr <= 1.0
