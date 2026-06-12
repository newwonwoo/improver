"""StackBrain 학습 — full-data 적합 후 outputs/stack_brain_models.pkl 저장.

CV F1(정직 측정)은 scripts/slm_stack_experiment.py 에서 산출한 OOF 값을 기록.
배포 임계값은 보정확률 기준 0.5 (isotonic 보정이라 0.5가 의미 있음) — 단,
OOF best-threshold 도 함께 저장해 운영자가 선택 가능.

실행: python scripts/train_stack_brain.py
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")

from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.isotonic import IsotonicRegression

from engine.slm.stack_brain import StackBrain, _CatStack, CATEGORIES
from scripts.slm_stack_experiment import (
    collect, _struct_logreg, _struct_poly, _text_tfidf, best_f1,
)


def _struct_matrix(struct_dicts, feat):
    return np.array([[s.get(k, 0.0) for k in feat] for s in struct_dicts])


def train():
    per_cat = collect()
    stacks: dict = {}
    print(f"{'cat':<8}{'n':>6}{'tp':>5}{'cv_f1':>8}{'thr':>7}")
    print("-" * 36)
    for cat in CATEGORIES:
        d = per_cat[cat]
        y = np.array(d["y"])
        n, tp = len(y), int(y.sum())
        if n < 40 or tp < 8 or (n - tp) < 8:
            print(f"{cat:<8}{n:>6}{tp:>5}  (표본 부족 — skip)")
            continue
        feat = list(d["struct"][0].keys())
        Xs = _struct_matrix(d["struct"], feat)
        texts = d["text"]
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

        # OOF 메타 피처 (누수 없는 base 확률) — meta/iso 적합 + cv_f1 측정용
        oof = np.zeros((n, 3))
        for tr, va in skf.split(Xs, y):
            bs = _struct_logreg().fit(Xs[tr], y[tr])
            bp = _struct_poly().fit(Xs[tr], y[tr])
            bt = _text_tfidf().fit([texts[i] for i in tr], y[tr])
            oof[va, 0] = bs.predict_proba(Xs[va])[:, 1]
            oof[va, 1] = bp.predict_proba(Xs[va])[:, 1]
            oof[va, 2] = bt.predict_proba([texts[i] for i in va])[:, 1]

        # 메타 + isotonic 보정 (OOF 위에서 적합)
        meta = LogisticRegression(C=1.0, max_iter=1000, class_weight="balanced").fit(oof, y)
        raw = meta.predict_proba(oof)[:, 1]
        iso = IsotonicRegression(out_of_bounds="clip").fit(raw, y)
        cal = iso.predict(raw)
        cv_f1, thr = best_f1(y, cal)

        # base 학습기 full-data 재적합 (배포용)
        base_s = _struct_logreg().fit(Xs, y)
        base_p = _struct_poly().fit(Xs, y)
        base_t = _text_tfidf().fit(texts, y)

        stacks[cat] = _CatStack(
            feature_names=feat, base_struct=base_s, base_poly=base_p,
            base_text=base_t, meta=meta, calibrator=iso,
            threshold=float(thr), cv_f1=float(cv_f1),
        )
        print(f"{cat:<8}{n:>6}{tp:>5}{cv_f1:>8.3f}{thr:>7.2f}")

    brain = StackBrain(stacks)
    brain.save()
    wsum = sum(s.cv_f1 * (np.array(per_cat[c]["y"]).shape[0])
               for c, s in stacks.items())
    ntot = sum(np.array(per_cat[c]["y"]).shape[0] for c in stacks)
    print("-" * 36)
    print(f"가중 CV F1 = {wsum / max(ntot,1):.3f}  →  저장: outputs/stack_brain_models.pkl")


if __name__ == "__main__":
    train()
