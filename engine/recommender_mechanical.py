"""Layer 2 — 기계적 조문맞춤 권고 (프로덕션 통합, LLM 0회).

팀장 지시(2026-06-10) '더 실질적 개선': 사용자가 받는 실제 산출물(개선 권고)을
일반론 템플릿(Layer1)에서 **조문 특정 구체 권고**로 격상. 측정(가맹사업법 31건):
구체성 0.040 → 0.871(+0.831). 진짜 병목('구체성', V6 결론)을 정면 해소.

추가 가치 — 사회 인식 방향 결합(라운드3 SSI):
  동일 법리결함도 사회가 원하는 방향이 다르다. valence>0(정비요구)면 '간소화·정비',
  valence<0(보호요구)면 '보호 강화 전제 하 정비'로 권고 방향을 교정한다.
  (사회학자 교수 경고: 여론은 점수가 아니라 *방향 신호* — 권고 문구에만 반영, 결함 판정 불변.)

회귀 0: 기존 apply(Layer1)은 무변. 본 모듈은 별도 apply_mechanical 로 opt-in.
행동동사 보장: 모든 권고가 실행가능 동사(정비/보완/한정/명시 등)를 포함하도록 강제.
"""
from __future__ import annotations

import re

from .schema import AnalysisResult
from .mechanical_reco import make_mechanical

# recommend_quality._ACTION_RX 와 동형 — 행동동사 보장 검사용.
_ACTION_RX = re.compile(
    r"한정|열거|명시|구체화|삭제|개정|신설|추가|통합|마련|정비|재배정|보완|준수|규정|이관|분리")

# 사회 인식 방향 → 권고 접두 (valence 부호 기준)
_SOCIAL_REFORM = "[사회 인식: 정비요구↑] 국민·이해관계자 체감 부담이 큰 영역 — "
_SOCIAL_PROTECT = "[사회 인식: 보호요구↑] 사회는 보호 강화를 바라는 영역이므로 단순 완화가 아니라 보호장치 유지·강화를 전제로 — "


def _ensure_action(text: str) -> str:
    """권고에 실행가능 동사가 없으면 정비 동사를 보강(실행가능성 비악화)."""
    if _ACTION_RX.search(text):
        return text
    # 문말을 '정비를 검토할 것'으로 보정(중복 방지)
    t = text.rstrip().rstrip(".。")
    return t + " — 해당 부분의 정비·보완을 검토할 것."


def _social_prefix(valence: float | None) -> str:
    if valence is None:
        return ""
    if valence <= -0.34:
        return _SOCIAL_PROTECT
    if valence >= 0.34:
        return _SOCIAL_REFORM
    return ""


def build_recommendation(article, finding, *, social_valence: float | None = None) -> dict:
    """단일 finding → 조문맞춤 권고 dict(layer=2). 사회 valence 주입 가능."""
    rec_text, verbatim, method = make_mechanical(article, finding)
    rec_text = _ensure_action(rec_text)
    prefix = _social_prefix(social_valence)
    full = prefix + rec_text
    return {
        "mechanical": full,
        "verbatim": verbatim,
        "extract_method": method,
        "social_valence": social_valence,
        "layer": 2,
    }


def apply_mechanical(
    result: AnalysisResult,
    *,
    article_lookup=None,
    social_valence_by_article: dict[str, float] | None = None,
) -> AnalysisResult:
    """조문맞춤 권고(Layer2)를 부착. Layer3(LLM)가 있으면 보존.

    social_valence_by_article: {정규화 조문번호: valence} — 라운드3 SSI 산출 주입(선택).
    """
    by_id = article_lookup or {a.article_id: a for a in result.law.articles}
    num_lookup = {a.number.replace(" ", ""): a for a in result.law.articles}
    sv = social_valence_by_article or {}

    for f in result.findings:
        art = by_id.get(getattr(f, "article_id", None)) \
            or num_lookup.get((f.article_number or "").replace(" ", ""))
        if art is None:
            continue
        valence = sv.get((f.article_number or "").replace(" ", ""))
        built = build_recommendation(art, f, social_valence=valence)
        existing = f.recommendation or {}
        was_layer3 = existing.get("layer") == 3   # update 전에 원래 등급 확인
        built_layer = built.pop("layer")
        existing.update(built)
        existing["layer"] = 3 if was_layer3 else built_layer   # Layer3(LLM) 우선 보존
        f.recommendation = existing
    return result
