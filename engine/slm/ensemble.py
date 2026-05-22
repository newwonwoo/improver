"""SLM-룰 앙상블 — 두 출력의 가중 결합.

설계:
- 룰 엔진 fire = 강한 신호 (verdict-fitted)
- SLM diagnose = 카테고리 신호 결합

결합 로직:
- 룰 fire OR (SLM score >= ensemble_threshold)
- SLM 단독 fire 는 임계값 더 높임 (정밀도 보호)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..schema import Article, Law, Finding
from .brain import CategoryBrain, CATEGORIES, analyze_article
from .features import extract_features


# 룰 ID → 카테고리
_RULE_CAT = {
    "S-01": "구조", "S-02": "구조", "S-03": "구조", "S-04": "구조",
    "F-01": "공정성", "F-02": "공정성", "F-03": "공정성", "F-04": "공정성", "F-05": "공정성",
    "L-01": "적법성", "L-02": "적법성", "L-03": "적법성",
    "G-01": "거버넌스", "G-02": "거버넌스", "G-03": "거버넌스", "G-04": "거버넌스", "G-05": "거버넌스",
    "E-01": "효율성", "E-02": "효율성", "E-03": "효율성", "E-04": "효율성", "E-05": "효율성",
}


@dataclass
class EnsembleVerdict:
    """앙상블 진단 결과."""
    article_number: str
    article_title: str
    category: str
    severity: str | None
    score: float
    source: str   # "rule" | "slm" | "both"


def _norm(s: str) -> str:
    return s.replace(" ", "").strip() if s else ""


# 카테고리별 SLM 단독 임계값 — 적법성·거버넌스는 SLM 신호 잡음 많아 높임
_CAT_SLM_THRESHOLD: dict[str, float] = {
    "구조": 0.70,
    "공정성": 0.70,
    "적법성": 0.85,   # cited_laws 신호 잡음 보호
    "거버넌스": 0.80,  # has_standard 신호 잡음 보호
    "효율성": 0.65,
}

# 룰 발화 시 SLM 확인 최저 임계값 — 이 값 미만이면 룰 단독 fire 억제
# 적법성: L-01/02/03 룰이 FP가 많아 SLM backing 필수
_RULE_CONFIRM_THRESHOLD: dict[str, float] = {
    "적법성": 0.35,
}


def ensemble_analyze(
    law: Law,
    findings: list[Finding],
    *,
    slm_threshold: float | None = None,
) -> dict[str, list[EnsembleVerdict]]:
    """룰 findings + SLM 분석 → 카테고리별 앙상블 진단.

    - rule fire 가 있으면 → "rule" 또는 "both"
    - rule fire 없지만 SLM score >= slm_threshold → "slm"
    - slm_threshold=None 시 카테고리별 _CAT_SLM_THRESHOLD 활용
    - 카테고리별 _RULE_CONFIRM_THRESHOLD 미만이면 룰 단독 fire 억제
    """
    # Rule fire 인덱스: (category, article_number) → [Finding...]
    rule_fires: dict[tuple[str, str], list[Finding]] = {}
    for f in findings:
        cat = _RULE_CAT.get(f.pattern_id)
        if not cat:
            continue
        key = (cat, _norm(f.article_number))
        rule_fires.setdefault(key, []).append(f)

    # SLM 분석
    results: dict[str, list[EnsembleVerdict]] = {c: [] for c in CATEGORIES}

    for art in law.articles:
        if art.is_definition() or art.is_purpose():
            continue
        diagnoses = analyze_article(art)
        for cat, diag in diagnoses.items():
            key = (cat, _norm(art.number))
            has_rule = key in rule_fires
            confirm_t = _RULE_CONFIRM_THRESHOLD.get(cat)
            # 룰 fire 가 있어도 confirm_t 설정 시 SLM 점수 확인 필요
            rule_confirmed = has_rule and (confirm_t is None or diag.score >= confirm_t)

            if rule_confirmed and diag.severity:
                src = "both"
                # 둘 다 발화 시 룰 심각도 우선
                best = max(rule_fires[key], key=lambda f: _SEV_ORDER.get(f.severity, 0))
                results[cat].append(EnsembleVerdict(
                    article_number=art.number,
                    article_title=art.title or "",
                    category=cat,
                    severity=best.severity,
                    score=max(diag.score, _SEV_TO_SCORE.get(best.severity, 0.5)),
                    source=src,
                ))
            elif rule_confirmed:
                best = max(rule_fires[key], key=lambda f: _SEV_ORDER.get(f.severity, 0))
                results[cat].append(EnsembleVerdict(
                    article_number=art.number,
                    article_title=art.title or "",
                    category=cat,
                    severity=best.severity,
                    score=_SEV_TO_SCORE.get(best.severity, 0.5),
                    source="rule",
                ))
            else:
                # SLM 단독 (또는 룰 fire 있으나 confirm 실패) — 카테고리별 임계값 적용
                t = slm_threshold if slm_threshold is not None else _CAT_SLM_THRESHOLD.get(cat, 0.75)
                if diag.score >= t:
                    results[cat].append(EnsembleVerdict(
                        article_number=art.number,
                        article_title=art.title or "",
                        category=cat,
                        severity=diag.severity,
                        score=diag.score,
                        source="slm",
                    ))
    return results


_SEV_ORDER = {"심각": 4, "경고": 3, "주의": 2, "개선": 1, None: 0}
_SEV_TO_SCORE = {"심각": 0.95, "경고": 0.80, "주의": 0.65, "개선": 0.50, None: 0.0}
