"""적용범위 신뢰도(Domain Scope Confidence) — 정직한 가드레일.

팀장 probe(2026-06-10): 민법총칙은 발화 적고 FP 소지 → 정직 표시 필요.
팀장 교정(2026-06-10): "주택법도 수집했는데 무슨 행정규제법 타령" — 정당한 지적.
  코퍼스 78%가 위임형 규제법령(주택법·건축법·가맹법…)으로 정상 적용범위.
  '행정규제법 전용'은 과소표현이었고, 위임율만으로 out_of_scope 판정은 과했다
  (정당법·헌법재판소법까지 배제). 교정: 강한 out_of_scope 는 **기본법전(민법·형법·
  상법·소송법류)** 에만, 그 외 저위임은 '참고(발화 적을 수 있음)'로 완화.

측정 근거(코퍼스 무작위 146개): in_scope 78% / borderline 12% / out_of_scope 10%.
엔진 대상 = 하위법령에 위임하는 규제법령(코퍼스 대다수). 진짜 범위 밖은 기본법전.

LLM 0회. 결함 판정·점수는 불변 — 본 모듈은 신뢰도 메타데이터만 부가(게이밍 0).
"""
from __future__ import annotations

import re

from .schema import Law

_DELEG_RX = re.compile(r"(대통령령|총리령|부령|시행령|시행규칙|고시)(?:으|)로\s*정")
# 기본법전·절차법 표지 — 사법(私法)·형사·소송 등 엔진과 결이 다른 근본법.
# 이것만이 강한 out_of_scope 신호(위임율과 무관하게 결함 taxonomy 자체가 다름).
_BASIC_CODE_HINT = re.compile(r"^(민법|상법|형법|민사소송법|형사소송법|행정소송법|"
                             r"민사집행법|비송사건절차법|국제사법|형의\s*집행)")

# 위임율 임계 — '신뢰도' 등급용(하드 배제 아님).
_DELEG_HIGH = 0.20
_DELEG_LOW = 0.05


def delegation_ratio(law: Law) -> float:
    """시행령·부령 위임 조문 비율 — 적용범위 신뢰도 신호."""
    arts = law.articles
    if not arts:
        return 0.0
    deleg = sum(1 for a in arts if _DELEG_RX.search(a.full_text or ""))
    return deleg / len(arts)


def scope_confidence(law: Law, *, finding_count: int | None = None) -> dict:
    """입력 법령의 엔진 적용범위 신뢰도.

    판정:
      out_of_scope : 기본법전(민·형·상·소송법류) — 결함 taxonomy 자체가 다름(강한 경고).
      in_scope     : 위임율 ≥ 0.20 — 위임형 규제법령(엔진 핵심 대상).
      borderline   : 그 외(저위임 비기본법) — 발화 적을 수 있으나 적용 가능(참고).
    결함 판정 불변, 메타데이터만.
    """
    dr = delegation_ratio(law)
    name = (law.name or "").strip()
    basic_hint = bool(_BASIC_CODE_HINT.match(name))
    n_arts = len(law.articles)

    if basic_hint:
        conf = "out_of_scope"
        reason = (f"기본법전/사법(私法)·절차법 표지('{name[:6]}') — 엔진 결함 taxonomy"
                  f"(포괄위임·청문누락·과도재량 등)와 결이 다름.")
        advisory = ("이 엔진은 하위법령 위임형 규제법령에 맞춰 설계됐습니다. 민·형·상사 기본법전은 "
                    "결함 개념 자체가 달라 신뢰도가 낮습니다 — 발화가 적은 것을 '결함 없음'으로, "
                    "발화한 것을 확정 결함으로 단정하지 마십시오(FP 소지 큼).")
    elif dr >= _DELEG_HIGH:
        conf = "in_scope"
        reason = f"위임율 {dr:.2f}(≥{_DELEG_HIGH}) — 하위법령 위임형 규제법령(엔진 핵심 대상)."
        advisory = ""
    else:
        conf = "borderline"
        reason = (f"위임율 {dr:.2f}(<{_DELEG_HIGH}) — 위임이 적은 규제법령. 적용 가능하나 "
                  f"발화가 적을 수 있음.")
        advisory = "위임 조항이 적어 탐지 결함 수가 적을 수 있습니다 — 결과를 참고로 검토하십시오."

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

