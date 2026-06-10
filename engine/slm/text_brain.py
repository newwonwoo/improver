"""TextBrain — char n-gram TF-IDF 텍스트 분류 (라운드2 자산, 분리·기본 OFF).

라운드1 측정으로 텍스트 피처가 정량신호 한계를 돌파(E4b 0.594 > 기존 0.551).
이 모듈은 그 모델을 추론에 쓰기 위한 로더다. **엔진 기본 경로는 건드리지 않는다**
(ensemble_analyze 무변) → 회귀 0. 활성화는 호출측의 명시적 게이트 결정.

학습/저장: scripts/train_text_brain.py → outputs/text_brain_models.pkl
"""
from __future__ import annotations

import pickle
from pathlib import Path

_MODEL_PATH = Path("outputs/text_brain_models.pkl")


class TextBrain:
    """저장된 TF-IDF + 카테고리별 LR 로 조문 텍스트의 카테고리 결함 확률 산출."""

    def __init__(self, bundle: dict):
        self.vectorizer = bundle["vectorizer"]
        self.models = bundle["models"]
        self.categories = bundle["categories"]
        self.text_win = set(bundle.get("text_win", []))

    @classmethod
    def load(cls, path: Path | str = _MODEL_PATH) -> "TextBrain | None":
        p = Path(path)
        if not p.exists():
            return None
        try:
            with open(p, "rb") as f:
                return cls(pickle.load(f))
        except (pickle.UnpicklingError, KeyError, EOFError):
            return None

    def score(self, text: str) -> dict[str, float]:
        """조문 텍스트 → {카테고리: 결함확률}. 미학습 카테고리는 생략."""
        if not text:
            return {}
        X = self.vectorizer.transform([text])
        out: dict[str, float] = {}
        for cat, clf in self.models.items():
            out[cat] = float(clf.predict_proba(X)[0, 1])
        return out

    def score_win_only(self, text: str) -> dict[str, float]:
        """텍스트가 측정상 우세한 카테고리만 반환(라운드1 nested 선택 근거)."""
        return {c: p for c, p in self.score(text).items() if c in self.text_win}
