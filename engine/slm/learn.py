"""SLM 학습 — sklearn LogisticRegression / MLPClassifier.

Phase 1: LogReg (선형 + sigmoid, learnable weights)
Phase 2: MLP (multi-layer, ReLU 비선형)

verdict 데이터에서 카테고리별 binary classifier 학습.
"""
from __future__ import annotations

import json
import pickle
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler, PolynomialFeatures
from sklearn.pipeline import Pipeline

from ..parser import parse_law
from ..structure import decompose
from .brain import CATEGORIES
from .features import extract_features


RULE_CAT = {
    "S-01": "구조", "S-02": "구조", "S-03": "구조", "S-04": "구조",
    "F-01": "공정성", "F-02": "공정성", "F-03": "공정성", "F-04": "공정성", "F-05": "공정성",
    "F-07": "공정성", "F-08": "공정성", "F-09": "공정성",
    "L-01": "적법성", "L-02": "적법성", "L-03": "적법성",
    "L-04": "적법성", "L-05": "적법성", "L-06": "적법성",
    "G-01": "거버넌스", "G-02": "거버넌스", "G-03": "거버넌스", "G-04": "거버넌스", "G-05": "거버넌스",
    "E-01": "효율성", "E-02": "효율성", "E-03": "효율성", "E-04": "효율성", "E-05": "효율성",
}

# 추론룰(R-*) → 카테고리. 출처: engine/reasoning/inference.py 룰 정의(단일 진실).
# phase13 verdict 라벨은 추론룰 네임스페이스라 RULE_CAT(패턴코드)와 별개 → 학습 적재용 보조맵.
REASONING_RULE_CAT = {
    "R-DELEG-BLANKET": "적법성",
    "R-DISP-ARBITRARY": "공정성",
    "R-NO-HEARING": "공정성",
    "R-DISPROPORTIONATE": "공정성",
    "R-DOUBLE-SANCTION": "적법성",
    "R-NO-REASON": "공정성",
    "R-NO-DEADLINE": "적법성",
    "R-ENUM-OVERLOAD": "구조",
    "R-PROVISO-EXCESS": "거버넌스",
    "R-CITATION-OVERLOAD": "적법성",
    "R-BROAD-IMMUNITY": "공정성",
    "R-HUB-DELEGATION": "적법성",
    "R-SHORT-DEADLINE-ADVERSE": "공정성",
    "R-SUBDELEG-ADMIN-RULE": "적법성",
    "R-NO-DISP-STANDARD": "공정성",
    "R-LAW-PRECEDENCE": "적법성",
}


def collect_training_data(test_size: float = 0.2, random_state: int = 42):
    """verdict 데이터에서 카테고리별 (X, y) 추출.

    X: feature matrix (n_samples × n_features)
    y: binary label (1=TP, 0=FP)

    Returns
    -------
    dict[cat] = (X_train, X_test, y_train, y_test, feature_names)
    """
    with open("outputs/verification_dataset.jsonl") as f:
        rows = [json.loads(l) for l in f]
    fid_map = json.loads(Path("outputs/fid_article_map.json").read_text(encoding="utf-8"))

    # 카테고리별 (feature_vec, label) 수집
    samples_per_cat: dict[str, list[tuple[dict, int]]] = defaultdict(list)

    # Law parse 캐시 (효율성)
    law_cache = {}

    def get_law(law_name: str):
        if law_name in law_cache:
            return law_cache[law_name]
        md = Path(f"data/laws/raw/{law_name}/법률.md")
        if not md.exists():
            law_cache[law_name] = None
            return None
        text = md.read_text(encoding="utf-8", errors="replace")
        if text.lstrip().startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                text = parts[2]
        try:
            law = parse_law(text, name=law_name)
            law_cache[law_name] = law
            return law
        except Exception:
            law_cache[law_name] = None
            return None

    for r in rows:
        if r["verdict"] not in ("TP", "FP"):
            continue
        rule_id = r["rule_id"]
        cat = RULE_CAT.get(rule_id)
        if not cat:
            continue
        fid = r["fid"]
        if "@" not in fid:
            continue
        _, law_name = fid.split("@", 1)
        an = fid_map.get(fid)
        if not an:
            continue
        law = get_law(law_name)
        if law is None:
            continue
        art = next((a for a in law.articles
                    if a.number.replace(" ", "") == an.replace(" ", "")), None)
        if not art:
            continue
        fv = extract_features(art).to_dict()
        label = 1 if r["verdict"] == "TP" else 0
        samples_per_cat[cat].append((fv, label))

    # numpy 변환 + train/test split
    out = {}
    feature_names = None
    for cat in CATEGORIES:
        samples = samples_per_cat[cat]
        if len(samples) < 20:
            continue
        # feature names 고정 (첫 샘플 기준)
        if feature_names is None:
            feature_names = list(samples[0][0].keys())
        X = np.array([[s[0].get(k, 0.0) for k in feature_names] for s in samples])
        y = np.array([s[1] for s in samples])
        try:
            X_tr, X_te, y_tr, y_te = train_test_split(
                X, y, test_size=test_size, random_state=random_state, stratify=y
            )
        except ValueError:
            # 클래스 한쪽만 있는 경우
            continue
        out[cat] = (X_tr, X_te, y_tr, y_te, feature_names)
    return out


def train_logistic(test_size: float = 0.2) -> dict[str, dict[str, Any]]:
    """Phase 1 — sklearn LogisticRegression per category."""
    data = collect_training_data(test_size=test_size)
    models = {}
    for cat, (X_tr, X_te, y_tr, y_te, feat_names) in data.items():
        pipe = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(
                C=1.0, max_iter=1000,
                class_weight="balanced", random_state=42,
            )),
        ])
        pipe.fit(X_tr, y_tr)
        y_pred = pipe.predict(X_te)
        y_proba = pipe.predict_proba(X_te)[:, 1]

        tp = int(((y_pred == 1) & (y_te == 1)).sum())
        fp = int(((y_pred == 1) & (y_te == 0)).sum())
        fn = int(((y_pred == 0) & (y_te == 1)).sum())
        tn = int(((y_pred == 0) & (y_te == 0)).sum())
        p = tp / max(tp + fp, 1)
        r = tp / max(tp + fn, 1)
        f1 = 2 * p * r / max(p + r, 1e-9)

        # weights 추출 (해석성)
        clf = pipe.named_steps["clf"]
        coefs = clf.coef_[0]
        weights = dict(zip(feat_names, coefs.tolist()))
        models[cat] = {
            "pipeline": pipe,
            "feature_names": feat_names,
            "weights": weights,
            "intercept": float(clf.intercept_[0]),
            "metrics": {
                "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                "precision": p, "recall": r, "f1": f1,
            },
            "n_train": len(y_tr), "n_test": len(y_te),
            "n_tp_train": int(y_tr.sum()), "n_fp_train": int((1 - y_tr).sum()),
        }
    return models


def _from_proba_threshold(y_proba, threshold: float):
    return (y_proba >= threshold).astype(int)


def _compute_metrics(y_pred, y_te):
    tp = int(((y_pred == 1) & (y_te == 1)).sum())
    fp = int(((y_pred == 1) & (y_te == 0)).sum())
    fn = int(((y_pred == 0) & (y_te == 1)).sum())
    tn = int(((y_pred == 0) & (y_te == 0)).sum())
    p = tp / max(tp + fp, 1)
    r = tp / max(tp + fn, 1)
    f1 = 2 * p * r / max(p + r, 1e-9)
    return dict(tp=tp, fp=fp, fn=fn, tn=tn, precision=p, recall=r, f1=f1)


def train_mlp(
    hidden_layers: tuple[int, ...] = (16,),
    test_size: float = 0.2,
) -> dict[str, dict[str, Any]]:
    """Phase 2 — sklearn MLPClassifier (ReLU + multi-layer).

    표본 부족 환경 — 단층 hidden(16) + threshold 튜닝 + class_weight 등가.
    """
    data = collect_training_data(test_size=test_size)
    models = {}
    for cat, (X_tr, X_te, y_tr, y_te, feat_names) in data.items():
        pipe = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", MLPClassifier(
                hidden_layer_sizes=hidden_layers,
                activation="relu",
                solver="adam",
                alpha=1e-2,                # 더 강한 L2
                max_iter=1000,
                early_stopping=True,
                validation_fraction=0.2,
                n_iter_no_change=30,
                random_state=42,
            )),
        ])
        pipe.fit(X_tr, y_tr)
        y_proba = pipe.predict_proba(X_te)[:, 1]
        # threshold 자동 튜닝: validation 분리 안 했으므로 0.4 표준 (recall 우선)
        # 표본 불균형에 따른 base rate 조정
        base_rate = y_tr.mean()
        threshold = max(0.30, min(0.55, base_rate * 1.5))
        y_pred = _from_proba_threshold(y_proba, threshold)
        m = _compute_metrics(y_pred, y_te)

        models[cat] = {
            "pipeline": pipe,
            "feature_names": feat_names,
            "n_layers": len(hidden_layers) + 1,
            "hidden_layers": list(hidden_layers),
            "threshold": threshold,
            "metrics": m,
            "n_train": len(y_tr), "n_test": len(y_te),
            "n_tp_train": int(y_tr.sum()), "n_fp_train": int((1 - y_tr).sum()),
        }
    return models


def train_mlp_smote(
    hidden_layers: tuple[int, ...] = (32, 16),
    test_size: float = 0.2,
):
    """Phase 7 — SMOTE 표본 불균형 보정 + MLP.

    minority class (TP) 를 합성으로 증강 후 학습.
    """
    try:
        from imblearn.over_sampling import SMOTE
    except ImportError:
        raise RuntimeError("imbalanced-learn not installed")

    data = collect_training_data(test_size=test_size)
    models = {}
    for cat, (X_tr, X_te, y_tr, y_te, feat_names) in data.items():
        # SMOTE 는 minority class 가 너무 적으면 실패 — k_neighbors 자동 조정
        n_tp = int(y_tr.sum())
        if n_tp < 6:
            continue
        k_neighbors = min(5, n_tp - 1)
        try:
            sm = SMOTE(random_state=42, k_neighbors=k_neighbors)
            X_res, y_res = sm.fit_resample(X_tr, y_tr)
        except Exception:
            X_res, y_res = X_tr, y_tr

        pipe = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", MLPClassifier(
                hidden_layer_sizes=hidden_layers,
                activation="relu",
                solver="adam",
                alpha=1e-2,
                max_iter=1000,
                early_stopping=True,
                validation_fraction=0.2,
                n_iter_no_change=30,
                random_state=42,
            )),
        ])
        pipe.fit(X_res, y_res)
        y_pred = pipe.predict(X_te)
        m = _compute_metrics(y_pred, y_te)

        models[cat] = {
            "pipeline": pipe,
            "feature_names": feat_names,
            "n_layers": len(hidden_layers) + 1,
            "hidden_layers": list(hidden_layers),
            "smote_applied": True,
            "n_train_original": len(y_tr),
            "n_train_resampled": len(y_res),
            "n_tp_train_original": n_tp,
            "n_tp_train_resampled": int(y_res.sum()),
            "metrics": m,
        }
    return models


def train_logreg_poly(degree: int = 2, test_size: float = 0.2):
    """Phase 1+ — Polynomial features (interaction) + LogReg.

    선형 모델이지만 polynomial features 로 비선형성 도입.
    """
    data = collect_training_data(test_size=test_size)
    models = {}
    for cat, (X_tr, X_te, y_tr, y_te, feat_names) in data.items():
        # interaction-only polynomial (degree=2 인 경우 x_i × x_j 만)
        pipe = Pipeline([
            ("scaler", StandardScaler()),
            ("poly", PolynomialFeatures(degree=degree, interaction_only=True,
                                        include_bias=False)),
            ("clf", LogisticRegression(
                C=0.5, max_iter=2000,
                class_weight="balanced",
                penalty="l2", random_state=42,
            )),
        ])
        pipe.fit(X_tr, y_tr)
        y_pred = pipe.predict(X_te)
        m = _compute_metrics(y_pred, y_te)
        models[cat] = {
            "pipeline": pipe,
            "feature_names": feat_names,
            "poly_degree": degree,
            "metrics": m,
            "n_train": len(y_tr), "n_test": len(y_te),
        }
    return models


def save_models(models: dict, path: str = "outputs/slm_learned_models.pkl"):
    with open(path, "wb") as f:
        pickle.dump(models, f)


def load_models(path: str = "outputs/slm_learned_models.pkl"):
    with open(path, "rb") as f:
        return pickle.load(f)
