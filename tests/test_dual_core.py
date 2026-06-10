"""이중심장(Dual-Core) 진단 테스트 — 팀장 '두 심장' 통찰의 구현 검증."""
from engine.parser import parse_law
from engine.reasoning.dual_core import (
    dual_core_diagnose,
    summarize_hearts,
    LEAD_HEART,
)
from engine.slm.brain import CATEGORIES

_LAW = """제1조(목적) 이 법은 시험을 목적으로 한다.
제5조(처분) 시장은 대통령령으로 정하는 바에 따라 영업정지를 명할 수 있다.
제6조(위임) 필요한 사항은 대통령령으로 정한다.
"""


def _law():
    return parse_law(_LAW, name="테스트법")


def test_every_category_has_a_lead_heart():
    # 두 심장이 모든 카테고리를 분담 — 종속 아닌 동격
    for cat in CATEGORIES:
        assert LEAD_HEART[cat] in ("reasoning", "neural")
    assert "reasoning" in LEAD_HEART.values()   # 추론 주도 영역 존재
    assert "neural" in LEAD_HEART.values()       # 신경망 주도 영역 존재


def test_dual_core_produces_per_category_verdicts():
    law = _law()
    art = next(a for a in law.articles if a.number == "제5조")
    d = dual_core_diagnose(art, law=law)
    assert set(d["categories"]) == set(CATEGORIES)
    for cat, v in d["categories"].items():
        assert v.lead_heart == LEAD_HEART[cat]
        assert 0.0 <= v.nn_score <= 1.0
        assert v.source in (None, "confirmed", "reasoning_lead", "neural_lead",
                            "reasoning_only", "nn_only")


def test_summarize_hearts_counts_sources():
    law = _law()
    art = next(a for a in law.articles if a.number == "제6조")
    d = dual_core_diagnose(art, law=law)
    s = summarize_hearts(d)
    assert set(s) == {"confirmed", "reasoning_lead", "neural_lead",
                      "reasoning_only", "nn_only"}
    assert all(isinstance(v, int) for v in s.values())


def test_dual_core_does_not_alter_production_path():
    """회귀0 불변식: 기존 ensemble_analyze 는 dual_core 를 참조하지 않는다."""
    import inspect
    from engine.slm import ensemble
    src = inspect.getsource(ensemble)
    assert "dual_core" not in src
