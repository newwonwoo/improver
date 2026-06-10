"""이중심장(Dual-Core) 진단 — 추론엔진과 신경망을 동격 심장으로 통합.

팀장 통찰(2026-06-10): "추론엔진과 신경망은 각각의 심장 아닌가."
기존 diagnose_with_reasoning 은 **추론 우선(reasoning-first)**: 법리 발화 시 신경망을
'회색지대(근거 약함)'로 격하 — 한쪽을 종속시키는 단일심장 구조.

라운드1 측정(outputs/text_boost_measure.json, e4b_nested_measure.json)은 두 심장이
**카테고리별로 상보적**임을 입증:
  - 공정성 → 룰/추론 심장이 더 강함(F1 0.680)
  - 구조·적법성·효율성·거버넌스 → 신경망/텍스트 심장이 더 강함(F1 0.49~0.65)

따라서 동격 설계: 각 심장이 *측정상 강한 카테고리를 주도(lead)* 하되, 두 심장이
모두 발화·일치하면 최강 신호(confirmed). 각 심장은 고유 장기 기능을 항상 기여한다 —
추론은 legal_basis(근거), 신경망은 회수(generalization).

기존 경로(ensemble_analyze, diagnose_with_reasoning) 무변 → 회귀 0. 본 모듈은 추가.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .inference import reason_over
from ..slm.brain import analyze_article, CATEGORIES
from ..structure import decompose
from ..slm.features import extract_features

_SEV_RANK = {"심각": 4, "경고": 3, "주의": 2, "개선": 1, None: 0}

# 라운드1 nested 게이팅 측정 결과 → 카테고리별 '주도 심장'.
# 출처: outputs/e4b_nested_measure.json (공정성=rule 우세, 그 외=텍스트/신경망 우세)
LEAD_HEART = {
    "공정성": "reasoning",   # 룰/법리 심장 주도
    "구조": "neural",
    "적법성": "neural",
    "거버넌스": "neural",
    "효율성": "neural",
}


@dataclass
class DualCoreVerdict:
    """한 조문·카테고리의 이중심장 통합 판정."""

    category: str
    lead_heart: str               # 'reasoning' | 'neural' — 측정상 주도 심장
    source: str                   # confirmed/reasoning_lead/neural_lead/reasoning_only/nn_only/None
    severity: str | None
    nn_score: float
    nn_severity: str | None
    reasoning_fired: bool
    legal_basis: list[str] = field(default_factory=list)
    reasoning_steps: list[dict] = field(default_factory=list)


def dual_core_diagnose(art, law=None, *, backend: str = "linear") -> dict:
    """추론엔진+신경망을 동격 심장으로 통합 진단.

    정책(단일심장 '추론우선'과의 차이):
      - 두 심장 모두 발화 + 일치 → 'confirmed' (최강).
      - 한쪽만 발화 →  그 카테고리의 *주도 심장*이면 정식 결함(_lead),
        주도 심장이 아니면 보조 신호(reasoning_only/nn_only — 재검토).
      - 심각도: 발화한 심장들 중 최댓값(둘 다면 max).
    """
    decomp = decompose(art)
    fv = extract_features(art, decomp, law=law)
    reasoning = reason_over(fv)
    reason_by_cat = reasoning.by_category()
    diagnoses = analyze_article(art, decomp, law=law, backend=backend)

    out = {"article_number": art.number, "article_title": art.title or "",
           "categories": {}}
    for cat in CATEGORIES:
        steps = reason_by_cat.get(cat, [])
        diag = diagnoses[cat]
        reason_fired = bool(steps)
        nn_fired = diag.severity is not None
        lead = LEAD_HEART.get(cat, "neural")

        reason_sev = None
        if reason_fired:
            reason_sev = max((s.severity for s in steps),
                             key=lambda s: _SEV_RANK.get(s, 0))

        if reason_fired and nn_fired:
            source = "confirmed"
            severity = (reason_sev if _SEV_RANK[reason_sev] >= _SEV_RANK[diag.severity]
                        else diag.severity)
        elif reason_fired:
            # 추론만 발화: 추론이 주도 심장이면 정식, 아니면 보조
            source = "reasoning_lead" if lead == "reasoning" else "reasoning_only"
            severity = reason_sev
        elif nn_fired:
            source = "neural_lead" if lead == "neural" else "nn_only"
            severity = diag.severity
        else:
            source = None
            severity = None

        out["categories"][cat] = DualCoreVerdict(
            category=cat,
            lead_heart=lead,
            source=source,
            severity=severity,
            nn_score=round(diag.score, 3),
            nn_severity=diag.severity,
            reasoning_fired=reason_fired,
            legal_basis=[s.legal_basis for s in steps],
            reasoning_steps=[{
                "premises": s.premises, "inference": s.inference,
                "conclusion": s.conclusion, "legal_basis": s.legal_basis,
                "confidence": s.confidence,
            } for s in steps],
        )
    out["reasoning_chain"] = reasoning.render()
    return out


def summarize_hearts(diagnosis: dict) -> dict:
    """이중심장 진단 → 심장별 기여 요약(설명용)."""
    counts = {"confirmed": 0, "reasoning_lead": 0, "neural_lead": 0,
              "reasoning_only": 0, "nn_only": 0}
    for cat, v in diagnosis["categories"].items():
        if v.source in counts:
            counts[v.source] += 1
    return counts
