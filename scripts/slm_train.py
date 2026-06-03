"""SLM 학습 CLI — Phase 1 (LogReg) + Phase 2 (MLP) 동시 학습 및 비교.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.slm.learn import (
    train_logistic, train_mlp, train_logreg_poly, train_mlp_smote, save_models,
)


def _print_metrics(label: str, models: dict):
    print(f"\n=== {label} ===")
    print(f"{'카테고리':<10} {'TP':>4} {'FP':>4} {'FN':>4} {'TN':>4} {'P':>6} {'R':>6} {'F1':>6} {'n_train':>9}")
    print("-" * 70)
    total_tp = total_fp = total_fn = total_tn = 0
    for cat, info in models.items():
        m = info["metrics"]
        total_tp += m["tp"]; total_fp += m["fp"]; total_fn += m["fn"]; total_tn += m["tn"]
        n_tr = info.get("n_train") or info.get("n_train_resampled") or info.get("n_train_original", 0)
        print(f"{cat:<10} {m['tp']:>4} {m['fp']:>4} {m['fn']:>4} {m['tn']:>4} "
              f"{m['precision']:>6.3f} {m['recall']:>6.3f} {m['f1']:>6.3f} "
              f"{n_tr:>9}")
    if total_tp + total_fp + total_fn + total_tn:
        p = total_tp / max(total_tp + total_fp, 1)
        r = total_tp / max(total_tp + total_fn, 1)
        f1 = 2 * p * r / max(p + r, 1e-9)
        print("-" * 70)
        print(f"{'TOTAL':<10} {total_tp:>4} {total_fp:>4} {total_fn:>4} {total_tn:>4} "
              f"{p:>6.3f} {r:>6.3f} {f1:>6.3f}")


def main():
    print("Phase 1: LogisticRegression 학습 ...")
    log_models = train_logistic()
    _print_metrics("Phase 1 — LogReg", log_models)

    print("\n\nPhase 1+: LogReg + Polynomial Features (degree=2) ...")
    poly_models = train_logreg_poly(degree=2)
    _print_metrics("Phase 1+ — LogReg + Poly degree=2 (interaction)", poly_models)

    print("\n\nPhase 2: MLPClassifier hidden=(16,) ReLU 학습 ...")
    mlp_models = train_mlp(hidden_layers=(16,))
    _print_metrics("Phase 2 — MLP (16,)", mlp_models)

    print("\n\nPhase 2+: MLPClassifier hidden=(32, 16) ReLU 학습 ...")
    mlp_deep = train_mlp(hidden_layers=(32, 16))
    _print_metrics("Phase 2+ — MLP (32, 16)", mlp_deep)

    print("\n\nPhase 7: SMOTE + MLP (32, 16) — 표본 불균형 보정 ...")
    mlp_smote = train_mlp_smote(hidden_layers=(32, 16))
    _print_metrics("Phase 7 — MLP+SMOTE (32, 16)", mlp_smote)

    print("\n\nPhase 7b: SMOTE + MLP (16,) ...")
    mlp_smote_s = train_mlp_smote(hidden_layers=(16,))
    _print_metrics("Phase 7b — MLP+SMOTE (16,)", mlp_smote_s)

    # 저장
    save_models(log_models, "outputs/slm_logreg_models.pkl")
    save_models(poly_models, "outputs/slm_poly_models.pkl")
    save_models(mlp_models, "outputs/slm_mlp_models.pkl")
    save_models(mlp_deep, "outputs/slm_mlp_deep_models.pkl")
    save_models(mlp_smote, "outputs/slm_mlp_smote_deep.pkl")
    save_models(mlp_smote_s, "outputs/slm_mlp_smote_shallow.pkl")
    print("\n저장 완료: outputs/slm_*_models.pkl")


if __name__ == "__main__":
    main()
