"""Rerank normalize + Sufficiency check — SLM 해석성 강화.

문제:
  1. 카테고리별 score 스케일 다름 (적법성 평균 0.3, 거버넌스 평균 0.5) → 직접 비교 불가
  2. score 단일 차원 → "왜 confident 한가" 의 추적 어려움

해결:
  - **Rerank normalize**: 카테고리별 calibration 통계 (mean·std) 기준 z-score 정규화
                        + sigmoid 로 [0,1] 복귀. 카테고리 간 비교 가능.
  - **Sufficiency check**: 다차원 confidence
      · feature_coverage: 영향 있는 신호 / 전체 가능 신호
      · prediction_margin: top1 score - 2nd top (또는 baseline)
      · graph_support: 그래프 신호 강도 (Phase 4 의 indegree+outdegree 기여)
      · signal_balance: 양수·음수 기여 신호 균형 (단방향 = 낮은 sufficiency)
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .brain import CategoryDiagnosis, CATEGORIES


# 카테고리별 calibration 통계 (verdict-fitted) — 부재시 도메인 기본값.
# slm_calibrate_v2.py 가 갱신하면 outputs/slm_score_stats.json 로 저장.
DEFAULT_SCORE_STATS: dict[str, dict[str, float]] = {
    # mean: 카테고리 평균 raw score (전 corpus 분석 기반 추정)
    # std : 표준편차. z = (x - mean) / std → sigmoid
    "구조":   {"mean": 0.40, "std": 0.20},
    "공정성":  {"mean": 0.30, "std": 0.18},
    "적법성":  {"mean": 0.25, "std": 0.17},
    "거버넌스": {"mean": 0.45, "std": 0.22},
    "효율성":  {"mean": 0.40, "std": 0.20},
}

_STATS_PATH = Path("outputs/slm_score_stats.json")


def _load_stats() -> dict[str, dict[str, float]]:
    if _STATS_PATH.exists():
        try:
            return json.loads(_STATS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULT_SCORE_STATS


def _sigmoid(x: float) -> float:
    # numerically stable
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


@dataclass
class Sufficiency:
    """진단 확신도의 다차원 분해."""
    feature_coverage: float = 0.0    # |contributing signals| / 전체 가능 신호
    prediction_margin: float = 0.0   # 결정 경계로부터 거리 (|score - 0.5| * 2)
    graph_support: float = 0.0       # 그래프 신호 기여 합 (절댓값)
    signal_balance: float = 0.0      # 1 - |pos_sum - neg_sum| / (pos_sum + neg_sum + ε)
    overall: float = 0.0             # 0~1 (위 4개 weighted sum)

    def to_dict(self) -> dict[str, float]:
        return {
            "feature_coverage": round(self.feature_coverage, 3),
            "prediction_margin": round(self.prediction_margin, 3),
            "graph_support": round(self.graph_support, 3),
            "signal_balance": round(self.signal_balance, 3),
            "overall": round(self.overall, 3),
        }


@dataclass
class RankedDiagnosis:
    """Rerank·Sufficiency 적용된 진단 결과."""
    category: str
    article_number: str
    article_title: str
    raw_score: float                 # CategoryBrain 의 원본 score (도메인 가중)
    normalized_score: float          # 카테고리 간 비교 가능 [0,1]
    severity: str | None
    sufficiency: Sufficiency
    contributing_signals: list[tuple[str, float]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "article_number": self.article_number,
            "article_title": self.article_title,
            "raw_score": round(self.raw_score, 3),
            "normalized_score": round(self.normalized_score, 3),
            "severity": self.severity,
            "sufficiency": self.sufficiency.to_dict(),
            "contributing_signals": [
                {"signal": s, "weight": round(w, 3)}
                for s, w in self.contributing_signals[:8]
            ],
        }


# 카테고리별 가능한 신호 수 (brain.WEIGHTS 길이) — feature_coverage 계산용
def _possible_signals_for(cat: str) -> int:
    from .brain import WEIGHTS
    return len(WEIGHTS.get(cat, {}))


def rerank_normalize(raw_score: float, category: str,
                     stats: dict[str, dict[str, float]] | None = None) -> float:
    """카테고리별 raw_score → 카테고리 간 비교 가능 normalized_score.

    z-score → sigmoid. mean 보다 클수록 normalized > 0.5.
    """
    if stats is None:
        stats = _load_stats()
    s = stats.get(category, DEFAULT_SCORE_STATS.get(category, {"mean": 0.4, "std": 0.2}))
    mean = float(s.get("mean", 0.4))
    std = float(s.get("std", 0.2))
    if std < 1e-6:
        std = 0.2
    z = (raw_score - mean) / std
    return _sigmoid(z)


def compute_sufficiency(diag: CategoryDiagnosis) -> Sufficiency:
    """단일 카테고리 진단 → 다차원 sufficiency."""
    sigs = diag.contributing_signals
    if not sigs:
        return Sufficiency()
    possible = max(_possible_signals_for(diag.category), 1)
    # 1. feature_coverage — 의미있는 기여 신호 비율 (절대 가중 >= 0.01)
    significant = [s for s in sigs if abs(s[1]) >= 0.01]
    coverage = min(len(significant) / possible, 1.0)
    # 2. prediction_margin — 결정 경계로부터 거리
    #    score 가 0.5 에서 멀수록 확실. severity threshold 0.45 / 0.60 / 0.75 / 0.90.
    margin = min(abs(diag.score - 0.5) * 2.0, 1.0)
    # 3. graph_support — 그래프 신호 기여의 절대합
    graph_sigs = [w for name, w in sigs if name.startswith("graph_")]
    graph_support = min(sum(abs(w) for w in graph_sigs) * 5.0, 1.0)  # scale up
    # 4. signal_balance — pos vs neg 신호 균형 (둘 다 있어야 robust)
    pos_sum = sum(w for _, w in sigs if w > 0)
    neg_sum = -sum(w for _, w in sigs if w < 0)
    total = pos_sum + neg_sum
    if total < 1e-6:
        balance = 0.0
    else:
        # 0 = 한쪽으로 완전 쏠림, 1 = 50:50
        balance = 1.0 - abs(pos_sum - neg_sum) / total

    # overall — 가중합 (margin 우선, coverage·balance 보조, graph_support 옵션)
    overall = (
        0.40 * margin +
        0.25 * coverage +
        0.20 * balance +
        0.15 * graph_support
    )
    overall = min(overall, 1.0)

    return Sufficiency(
        feature_coverage=coverage,
        prediction_margin=margin,
        graph_support=graph_support,
        signal_balance=balance,
        overall=overall,
    )


def reclassify_severity(normalized_score: float, sufficiency: Sufficiency) -> str | None:
    """Normalized score + sufficiency 기반 severity 재분류.

    낮은 sufficiency 면 한 등급 강등 (false-positive 완화).
    """
    score = normalized_score
    if sufficiency.overall < 0.30:
        # 매우 낮은 확신 → 결과 무효화
        return None
    if score >= 0.85:
        sev = "심각"
    elif score >= 0.70:
        sev = "경고"
    elif score >= 0.55:
        sev = "주의"
    elif score >= 0.40:
        sev = "개선"
    else:
        return None

    if sufficiency.overall < 0.50:
        # 보통 확신 → 한 등급 강등
        downgrade = {"심각": "경고", "경고": "주의", "주의": "개선", "개선": None}
        sev = downgrade.get(sev, sev)
    return sev


def rank_diagnoses(
    diagnoses: dict[str, CategoryDiagnosis],
    stats: dict[str, dict[str, float]] | None = None,
) -> dict[str, RankedDiagnosis]:
    """5개 카테고리 CategoryDiagnosis → RankedDiagnosis (rerank + sufficiency).

    카테고리 간 normalized_score 비교 가능 + sufficiency 다차원 추적.
    """
    if stats is None:
        stats = _load_stats()
    out: dict[str, RankedDiagnosis] = {}
    for cat, diag in diagnoses.items():
        norm = rerank_normalize(diag.score, cat, stats)
        suff = compute_sufficiency(diag)
        sev = reclassify_severity(norm, suff)
        out[cat] = RankedDiagnosis(
            category=cat,
            article_number=diag.article_number,
            article_title=diag.article_title,
            raw_score=diag.score,
            normalized_score=norm,
            severity=sev,
            sufficiency=suff,
            contributing_signals=list(diag.contributing_signals),
        )
    return out


def top_category(ranked: dict[str, RankedDiagnosis]) -> str | None:
    """카테고리 간 비교 가능해진 normalized_score 기준 top-1."""
    if not ranked:
        return None
    # severity 가 있는 카테고리 우선, 그 다음 normalized_score 내림차순
    sev_order = {"심각": 4, "경고": 3, "주의": 2, "개선": 1, None: 0}
    return max(
        ranked.keys(),
        key=lambda c: (sev_order.get(ranked[c].severity, 0), ranked[c].normalized_score),
    )
