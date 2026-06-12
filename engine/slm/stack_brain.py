"""StackBrain — 다중신호 OOF 스태킹 + 확률보정 (추론엔진 강화, opt-in).

측정 근거(scripts/slm_stack_experiment.py, 5-fold OOF best-threshold F1):
  struct=0.500 · poly=0.432 · text=0.556 · **STACK=0.575** (가중평균).
  → 기존 구조특징 단일(0.500) 대비 +0.075, 최강 단일 text(0.556) 대비 +0.019,
    게다가 isotonic 보정으로 '신뢰도=실제 확률' 약점 해소.

설계 원칙(text_brain 과 동일):
  - 엔진 기본 경로(backend="linear")는 건드리지 않는다. 명시적 opt-in 만.
  - base 학습기: 구조 LogReg / 구조 Poly-interaction / 텍스트 TF-IDF(char n-gram).
  - meta: LogReg(균일 스택) + IsotonicRegression(폴드 외 전체 재적합 보정).
  - LLM 0회. sklearn 만 사용.

학습: scripts/train_stack_brain.py → outputs/stack_brain_models.pkl
추론: StackBrain.load().score_article(art) → {category: calibrated_proba}
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .features import extract_features

_MODEL_PATH = "outputs/stack_brain_models.pkl"
CATEGORIES = ["구조", "공정성", "적법성", "거버넌스", "효율성"]


@dataclass
class _CatStack:
    """한 카테고리의 스택 — base 파이프라인들 + 메타 + 보정 + feature 순서."""
    feature_names: list
    base_struct: object        # Pipeline (구조 LogReg)
    base_poly: object          # Pipeline (구조 Poly-interaction LogReg)
    base_text: object          # Pipeline (TF-IDF LogReg)
    meta: object               # LogisticRegression on [s,p,t] proba
    calibrator: object | None  # IsotonicRegression or None
    threshold: float           # OOF best-F1 임계값
    cv_f1: float               # 학습 시 측정된 OOF F1 (정직성 기록)

    def proba(self, fv_dict: dict, text: str) -> float:
        xs = np.array([[fv_dict.get(k, 0.0) for k in self.feature_names]])
        ps = self.base_struct.predict_proba(xs)[:, 1]
        pp = self.base_poly.predict_proba(xs)[:, 1]
        pt = self.base_text.predict_proba([text])[:, 1]
        m = np.column_stack([ps, pp, pt])
        raw = self.meta.predict_proba(m)[:, 1]
        if self.calibrator is not None:
            raw = self.calibrator.predict(raw)
        return float(raw[0])


class StackBrain:
    """opt-in 스택 브레인 — 카테고리별 보정 확률 산출."""

    def __init__(self, stacks: dict):
        self.stacks: dict[str, _CatStack] = stacks

    @classmethod
    def load(cls, path: str = _MODEL_PATH) -> "StackBrain | None":
        p = Path(path)
        if not p.exists():
            return None
        with open(p, "rb") as f:
            return cls(pickle.load(f))

    def save(self, path: str = _MODEL_PATH) -> None:
        with open(path, "wb") as f:
            pickle.dump(self.stacks, f)

    def score_article(self, art) -> dict[str, float]:
        """조문 → {카테고리: 보정확률}. 학습된 카테고리만 반환."""
        fv = extract_features(art).to_dict()
        text = art.full_text or ""
        return {cat: st.proba(fv, text) for cat, st in self.stacks.items()}

    def diagnose_article(self, art) -> dict[str, dict]:
        """score + 임계값 판정(결함 여부) + 학습시 OOF F1 동봉."""
        fv = extract_features(art).to_dict()
        text = art.full_text or ""
        out = {}
        for cat, st in self.stacks.items():
            p = st.proba(fv, text)
            out[cat] = {"proba": p, "is_defect": p >= st.threshold,
                        "threshold": st.threshold, "cv_f1": st.cv_f1}
        return out
