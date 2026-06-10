"""SSI(사회 현저성) 레이어 테스트 — 회의 합의 + 감사인 4조건 검증."""
from engine.social import compute_ssi, extract_topic_terms, score_valence


def test_topic_terms_strip_admin_boilerplate():
    text = "환경부장관은 대통령령으로 정하는 바에 따라 자동차 배출가스 검사를 실시하여야 한다."
    terms = extract_topic_terms(text, top_k=5)
    assert "대통령령" not in terms          # 행정 상투어 제거
    assert any("배출" in t or "자동차" in t or "검사" in t for t in terms)


def test_valence_reform_vs_protect():
    reform = ["이 규제가 너무 과도하고 불편하다는 민원", "복잡한 절차 간소화 요구"]
    protect = ["취약계층 보호 강화 필요", "안전 사각지대 피해 예방"]
    v_r, dr, _ = score_valence(reform)
    v_p, _, dp = score_valence(protect)
    assert v_r > 0 and dr > 0                # 정비요구 우세
    assert v_p < 0 and dp > 0                # 보호요구 우세
    assert score_valence([])[0] == 0.0       # 무근거 시 중립


def test_ssi_without_search_uses_reach_only():
    text = "사업자는 영업을 신고하여야 한다."
    r = compute_ssi("제5조", text, search_fn=None)
    assert r.reach_citizen is True           # 신고 = 국민·사업자 대면
    assert r.hit_count == 0                   # 검색 미수행
    assert 0.0 <= r.ssi <= 1.0


def test_ssi_with_stub_search_is_bounded_and_records_sources():
    def stub(q):
        return [
            {"title": "낡은 규제 불편 개선 요구", "desc": "복잡한 절차 부담", "url": "u1"},
            {"title": "중복규제 철폐 민원", "desc": "과도한 부담", "url": "u1"},  # 중복 url
            {"title": "관련 안전 보호 강화", "desc": "피해 예방", "url": "u2"},
        ]
    r = compute_ssi("제10조", "사업자 등록 신청 절차", search_fn=stub, period="2026-05~06")
    assert r.hit_count == 2                   # url 중복 제거
    assert 0.0 <= r.ssi <= 1.0
    assert len(r.sources) == 2                # 원자료 보존(감사 조건3)
    assert r.salience > 0


def test_ssi_is_pure_no_findings_side_effects():
    """감사 조건1: SSI 는 findings 를 만들지 않는다(F1 영향 0)."""
    r = compute_ssi("제1조", "행정청 내부 보고 절차", search_fn=lambda q: [])
    # SocialSalience 는 finding/severity 속성을 갖지 않음 — 탐지층과 완전 분리
    assert not hasattr(r, "severity")
    assert not hasattr(r, "is_false_positive")
