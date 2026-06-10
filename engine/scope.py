"""적용범위 신뢰도(Domain Scope Confidence) — 정직한 가드레일.

팀장 probe(2026-06-10, 민법총칙): 행정규제법용 엔진에 사법(私法)·기본법을 넣으면
발화가 적고 신뢰도가 낮다 — 이를 '깨끗함'으로 오인하지 않도록 정직하게 표시.

측정 근거(실측):
  행정규제법(가맹·119): 위임율(시행령·부령 위임 조문 비율) 0.39~0.58, 발화율 0.58~0.61
  기본법(민법·상법·형법): 위임율 0.00~0.03, 발화율 0.03~0.07
→ 위임 밀도가 적용범위의 강한 판별자. 엔진은 '하위법령에 위임하는 행정규제'가 대상.

LLM 0회. 결함 판정·점수는 불변 — 본 모듈은 신뢰도 메타데이터만 부가(게이밍 0).
"""
from __future__ import annotations

import re

from .schema import Law

_DELEG_RX = re.compile(r"(대통령령|총리령|부령|시행령|시행규칙|고시)(?:으|)로\s*정")
# 사법·기본법 표지(제목 기반 보조 신호) — 단독 판정 아님, 위임율과 결합.
_BASIC_CODE_HINT = re.compile(r"^(민법|상법|형법|민사소송법|형사소송법|행정소송법|"
                             r"국민의 형사재판|군사법원법)")

# 임계(실측 경계): 위임율 0.03(기본법 최대) ~ 0.39(행정법 최소) 사이를 회색대로.
_DELEG_LOW = 0.05
_DELEG_HIGH = 0.20


def delegation_ratio(law: Law) -> float:
    """시행령·부령 위임 조문 비율 — 적용범위 핵심 신호."""
    arts = law.articles
    if not arts:
        return 0.0
    deleg = sum(1 for a in arts if _DELEG_RX.search(a.full_text or ""))
    return deleg / len(arts)


def scope_confidence(law: Law, *, finding_count: int | None = None) -> dict:
    """입력 법령이 엔진 적용범위(행정규제법)에 부합하는 신뢰도.

    반환: {confidence: in_scope|borderline|out_of_scope, delegation_ratio,
           reason, advisory} — 결함 판정 불변, 메타데이터만.
    """
    dr = delegation_ratio(law)
    name = (law.name or "").strip()
    basic_hint = bool(_BASIC_CODE_HINT.match(name))
    n_arts = len(law.articles)

    if dr >= _DELEG_HIGH and not basic_hint:
        conf = "in_scope"
        reason = f"위임율 {dr:.2f}(≥{_DELEG_HIGH}) — 하위법령 위임형 행정규제법 패턴."
        advisory = ""
    elif dr < _DELEG_LOW or basic_hint:
        conf = "out_of_scope"
        why = []
        if basic_hint:
            why.append("기본법/사법(私法) 표지")
        if dr < _DELEG_LOW:
            why.append(f"위임율 {dr:.2f}(<{_DELEG_LOW}) — 거의 위임 없음")
        reason = " + ".join(why) + " → 엔진 적용범위(행정규제법) 밖."
        advisory = ("이 엔진의 룰·학습데이터는 행정규제법(포괄위임·청문누락·과도재량 등) "
                    "전용입니다. 사법·기본법의 결함 판정은 신뢰도가 낮으며, 발화가 적은 것을 "
                    "'결함 없음'으로 해석하지 마십시오. 발화한 결함도 오탐(FP) 소지가 큽니다.")
    else:
        conf = "borderline"
        reason = f"위임율 {dr:.2f}({_DELEG_LOW}~{_DELEG_HIGH}) — 경계 영역."
        advisory = "적용범위 경계 — 결과를 비판적으로 검토하십시오."

    out = {
        "confidence": conf,
        "delegation_ratio": round(dr, 4),
        "n_articles": n_arts,
        "reason": reason,
        "advisory": advisory,
    }
    if finding_count is not None:
        out["finding_rate"] = round(finding_count / max(n_arts, 1), 4)
    return out
