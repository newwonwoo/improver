"""S6 — 개선안(권고) 품질 채점기.

Layer1(템플릿)·Layer3(LLM 맥락화)가 만든 개선안이 실제로 쓸모있는지
{정확·구체·실행가능} 3축으로 결정적 채점(LLM 불요). 저품질 자동 플래그.

설계서: docs/design/TF_redesign_plan_v1.md (S6).
사람 라벨 20건 기준선과 상관(≥0.6) 측정은 별도 평가 루프에서 수행.
"""
from __future__ import annotations
import re

# 실행 동사 — "무엇을 어떻게 고쳐라"가 들어있는지
_ACTION_RX = re.compile(
    r"한정|열거|명시|구체화|삭제|개정|신설|추가|통합|마련|정비|재배정|보완|준수|규정|이관|분리"
)
# 구체 참조 — 특정 조·항·호·별표를 가리키는지
_ARTICLE_REF_RX = re.compile(r"제\s*\d+\s*조|제\s*\d+\s*항|각\s*호|별표|단서")
# 일반론 보일러플레이트 — 정확도 감점
_GENERIC = ("조치 불요", "기회 있을 때", "검토 필요", "검토 바람", "필요시 검토")


def score_recommendation(text: str, *, article_ref: str | None = None) -> dict:
    """개선안 텍스트 → 3축 점수 + 저품질 플래그.

    article_ref: 해당 조문 번호(예: '제3조'). 주어지면 구체성 보강 판정에 사용.
    """
    t = (text or "").strip()
    if not t:
        return {"specificity": 0.0, "actionability": 0.0, "accuracy": 0.0,
                "overall": 0.0, "low_quality": True}

    # 구체성: 조문 참조 + 인용부호(특정 문구 지목) + 수치
    specificity = 0.0
    if _ARTICLE_REF_RX.search(t) or (article_ref and article_ref in t):
        specificity += 0.5
    if any(q in t for q in ("'", '"', "“", "「")):
        specificity += 0.25
    if re.search(r"\d", t):
        specificity += 0.25
    specificity = min(1.0, specificity)

    # 실행가능성: 구체 동작 동사 존재
    actionability = 1.0 if _ACTION_RX.search(t) else 0.0

    # 정확성(프록시): 일반론·과도하게 짧음 감점
    accuracy = 1.0
    if any(g in t for g in _GENERIC):
        accuracy -= 0.5
    if len(t) < 15:
        accuracy -= 0.5
    accuracy = max(0.0, accuracy)

    overall = round((specificity + actionability + accuracy) / 3, 3)
    return {
        "specificity": round(specificity, 3),
        "actionability": round(actionability, 3),
        "accuracy": round(accuracy, 3),
        "overall": overall,
        "low_quality": overall < 0.5,
    }


def score_findings(findings: list) -> list[dict]:
    """finding 리스트의 개선안(template/contextual)을 일괄 채점."""
    out = []
    for f in findings:
        rec = (getattr(f, "contextual", None) or getattr(f, "template", None)
               or (f.get("contextual") or f.get("template") if isinstance(f, dict) else None) or "")
        ref = getattr(f, "article_number", None) or (f.get("article") if isinstance(f, dict) else None)
        s = score_recommendation(rec, article_ref=ref)
        s["recommendation"] = rec
        out.append(s)
    return out
