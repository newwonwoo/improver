"""Layer2 조문맞춤 권고(프로덕션 통합) 테스트 — 구체성↑·행동동사 보장·회귀0."""
from engine.parser import parse_law
from engine.rules import run_all
from engine.recommender import apply as apply_template
from engine.recommender_mechanical import (
    apply_mechanical,
    build_recommendation,
    _ensure_action,
)
from engine.recommend_quality import score_recommendation
from engine.schema import AnalysisResult

_LAW = """제6조의5(가맹금 예치 등) ① 가맹본부는 가맹금을 예치하여야 한다.
② 그 밖에 가맹금의 예치 등에 관하여 필요한 사항은 대통령령으로 정한다.
"""


def _result():
    law = parse_law(_LAW, name="테스트법")
    findings = run_all(law)
    return AnalysisResult(law=law, findings=findings, category_scores={},
                          article_scores=[], law_score=0.0, law_grade="Clean"), law


def test_ensure_action_adds_verb_when_missing():
    assert "정비" in _ensure_action("제3조 본문 「가나다」")        # 동사 없음 → 보강
    kept = _ensure_action("제3조 본문 「가나다」 정비를 검토할 것.")
    assert kept.count("정비") >= 1                                   # 이미 있으면 중복보강 안 함


def test_mechanical_more_specific_than_template():
    res, law = _result()
    if not res.findings:
        return
    f = res.findings[0]
    art = next(a for a in law.articles if a.number.replace(" ", "")
               == f.article_number.replace(" ", ""))
    built = build_recommendation(art, f)
    m = score_recommendation(built["mechanical"], article_ref=f.article_number)
    # 조문 인용 → 구체성 확보
    assert m["specificity"] >= 0.5
    assert built["layer"] == 2


def test_social_valence_changes_direction_prefix():
    res, law = _result()
    if not res.findings:
        return
    f = res.findings[0]
    art = next(a for a in law.articles if a.number.replace(" ", "")
               == f.article_number.replace(" ", ""))
    protect = build_recommendation(art, f, social_valence=-1.0)
    reform = build_recommendation(art, f, social_valence=+1.0)
    neutral = build_recommendation(art, f, social_valence=None)
    assert "보호" in protect["mechanical"]
    assert "정비요구" in reform["mechanical"]
    assert protect["mechanical"] != reform["mechanical"] != neutral["mechanical"]


def test_apply_mechanical_attaches_layer2_and_preserves_layer3():
    res, law = _result()
    # Layer3 가짜 부착 → 보존되는지
    if res.findings:
        res.findings[0].recommendation = {"contextual": "LLM맞춤", "layer": 3}
    apply_mechanical(res)
    for f in res.findings:
        assert f.recommendation is not None
        if f.recommendation.get("contextual") == "LLM맞춤":
            assert f.recommendation["layer"] == 3       # Layer3 보존
        else:
            assert f.recommendation["layer"] == 2


def test_template_apply_unchanged_regression():
    """회귀0: 기존 Layer1 apply 는 mechanical 을 참조하지 않는다."""
    import inspect
    import engine.recommender as r
    assert "mechanical" not in inspect.getsource(r.apply)
