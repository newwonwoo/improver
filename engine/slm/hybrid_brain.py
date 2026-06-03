"""하이브리드 신경망 — 카테고리별 best-model 선택 앙상블.

Step 76 평가 결과 기반:
- 적법성: MLP (32,16) 가 hand-tuned 보다 +0.059 — MLP 채택
- 효율성: MLP (16,)   가 hand-tuned 보다 +0.019 — MLP 채택
- 구조·공정성·거버넌스: hand-tuned 가 우세 — 그대로

룰 엔진 + hybrid SLM 앙상블이 최적.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..schema import Article
from ..structure import decompose
from .brain import (
    CATEGORIES, CategoryBrain, CategoryDiagnosis,
    _classify_severity,
)
from .features import extract_features
from .learn import load_models


# 카테고리별 best 모델 선택 (Step 76 결과 기반)
_BEST_MODEL_PATH = {
    "적법성": ("outputs/slm_mlp_deep_models.pkl", "mlp"),
    "효율성": ("outputs/slm_mlp_models.pkl", "mlp"),
    # 구조·공정성·거버넌스: hand-tuned (CategoryBrain.for_category)
}


def _try_load(path: str):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return load_models(path)
    except Exception:
        return None


# 학습된 모델 캐시
_LEARNED_CACHE: dict[str, dict] = {}


def _get_learned_model(cat: str):
    if cat in _LEARNED_CACHE:
        return _LEARNED_CACHE[cat]
    if cat not in _BEST_MODEL_PATH:
        _LEARNED_CACHE[cat] = None
        return None
    path, kind = _BEST_MODEL_PATH[cat]
    models = _try_load(path)
    if not models or cat not in models:
        _LEARNED_CACHE[cat] = None
        return None
    info = models[cat]
    info["kind"] = kind
    _LEARNED_CACHE[cat] = info
    return info


def diagnose_hybrid(art: Article) -> dict[str, CategoryDiagnosis]:
    """하이브리드 진단: 카테고리별 best-model.

    적법성·효율성: 학습된 MLP 의 predict_proba
    구조·공정성·거버넌스: hand-tuned CategoryBrain
    """
    decomp = decompose(art)
    fv = extract_features(art, decomp)
    fv_dict = fv.to_dict()
    out: dict[str, CategoryDiagnosis] = {}
    for cat in CATEGORIES:
        learned = _get_learned_model(cat)
        if learned is not None:
            # 학습된 모델 사용
            feat_names = learned["feature_names"]
            x = np.array([[fv_dict.get(k, 0.0) for k in feat_names]])
            try:
                proba = learned["pipeline"].predict_proba(x)[0, 1]
                threshold = learned.get("threshold", 0.5)
                score = float(proba)
                severity = _classify_severity(score) if score >= threshold else None
                out[cat] = CategoryDiagnosis(
                    category=cat,
                    article_number=art.number,
                    article_title=art.title or "",
                    score=score,
                    severity=severity,
                    confidence=float(abs(proba - 0.5) * 2),
                    contributing_signals=[("learned_model", proba)],
                )
                continue
            except Exception:
                pass
        # Fallback: hand-tuned CategoryBrain
        brain = CategoryBrain.for_category(cat)
        out[cat] = brain.forward(fv)
    return out
