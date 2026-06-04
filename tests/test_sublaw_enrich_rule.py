"""enrich_with_sublaw: 시행령 + 시행규칙 한정열거 감지 (R-DELEG-BLANKET FP 필터).

P-META-1(시행령) + 확장(시행규칙). 실제 코퍼스(data/laws/raw) 기반.
"""
from engine.slm.features import FeatureVector, enrich_with_sublaw, _SUBLAW_CACHE


def setup_function(_):
    _SUBLAW_CACHE.clear()


def test_enrich_via_sihaenggyuchik():
    # 산안법 제130조 단서 위임 → 시행규칙 제200조 '다음 각 호' 한정열거.
    # 시행령엔 법 제130조 인용 없음 → 시행령만 읽던 기존 코드는 못 잡던 케이스.
    fv = FeatureVector()
    enrich_with_sublaw(fv, "산업안전보건법", "제130조")
    assert fv.has_sublaw_concrete_enum == 1.0


def test_enrich_via_sihaengryeong_regression():
    # 주택법 제12조 위임 → 시행령 한정열거 (기존 P-META-1 경로 회귀 확인).
    fv = FeatureVector()
    enrich_with_sublaw(fv, "주택법", "제12조")
    assert fv.has_sublaw_concrete_enum == 1.0


def test_enrich_no_sublaw_stays_zero():
    fv = FeatureVector()
    enrich_with_sublaw(fv, "존재하지않는법령ZZZ", "제1조")
    assert fv.has_sublaw_concrete_enum == 0.0
