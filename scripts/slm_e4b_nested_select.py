"""E4b — 내부 CV(nested) 기반 카테고리별 선택 게이팅 (E4 설계결함 교정).

E4 실패 원인(실측): in-sample train F1 로 후보를 고르니 과적합 모델(부스팅)이
전 카테고리에서 선택됨(train F1≈1) → OOF total 0.489. 교정: 선택을 **train fold
내부 3-fold CV 성능**으로 결정(후보 모델이 보지 못한 데이터 기준 — 누수·편향 0).

후보: {rule, e1(텍스트 TF-IDF+LR), rule∨e1}.
e2/e3 제외 근거(측정): OOF에서 단 한 카테고리도 e1·rule 둘 다를 유의하게 못 이김
(구조 e3 0.528 vs e1 0.492 — CI 대폭 겹침), dense 피처 재계산엔 전체 파싱 필요.

프로토콜: V0' 동일 잣대. outer fold 는 text_boost 실험과 동일(seed 42).
입력: outputs/text_boost_rows.jsonl(텍스트), outputs/text_boost_oof.npz(y, rule_pred)
출력: outputs/e4b_nested_measure.json + npz 에 oof_e4b 추가
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_sys.path.insert(0, _ROOT)
_sys.path.insert(0, _os.path.join(_ROOT, "scripts"))

from engine.slm.brain import CATEGORIES
from engine.slm.torch_brain import _prf
from v0prime_fair_rule_baseline import oof_score, _fmt
from slm_text_boost_experiment import fold_splits, _f1_binary


def _make_vec():
    from sklearn.feature_extraction.text import TfidfVectorizer
    return TfidfVectorizer(analyzer="char", ngram_range=(2, 4),
                           max_features=2000, sublinear_tf=True, min_df=2)


def _fit_lr(Xtr, ytr, Xte):
    from sklearn.linear_model import LogisticRegression
    clf = LogisticRegression(max_iter=2000, class_weight="balanced")
    clf.fit(Xtr, ytr)
    return (clf.predict_proba(Xte)[:, 1] >= 0.5).astype(np.float32)


def main():
    rows = [json.loads(l) for l in open("outputs/text_boost_rows.jsonl", encoding="utf-8")]
    texts = np.array([r["text"] for r in rows], dtype=object)
    npz = dict(np.load("outputs/text_boost_oof.npz"))
    y, rule_pred = npz["y"], npz["rule_pred"]
    n = len(rows)
    print(f"[E4b] nested 선택 게이팅 — N={n}")

    splits = fold_splits(y)
    oof_e4b = np.zeros((n, len(CATEGORIES)), dtype=np.float32)
    choice_log = []

    from sklearn.model_selection import KFold

    for fold_i, (tr, te) in enumerate(splits):
        # ── 내부 3-fold: train fold 안에서 후보별 OOF 성능 측정 ──
        inner = KFold(n_splits=3, shuffle=True, random_state=42)
        e1_inner = np.zeros((len(tr), len(CATEGORIES)), dtype=np.float32)
        for itr, ite in inner.split(np.zeros(len(tr))):
            g_itr, g_ite = tr[itr], tr[ite]
            vec = _make_vec()
            Xitr = vec.fit_transform(texts[g_itr])
            Xite = vec.transform(texts[g_ite])
            for ci in range(len(CATEGORIES)):
                m = y[g_itr, ci] >= 0
                yt = y[g_itr, ci][m]
                if (yt == 1).sum() < 2 or (yt == 0).sum() < 2:
                    continue
                e1_inner[ite, ci] = _fit_lr(Xitr[m], yt, Xite)

        rule_inner = rule_pred[tr]
        cand_inner = {"rule": rule_inner, "e1": e1_inner,
                      "rule|e1": np.maximum(rule_inner, e1_inner)}

        # ── outer test 예측용: train 전체로 e1 학습 ──
        vec = _make_vec()
        Xtr_full = vec.fit_transform(texts[tr])
        Xte_full = vec.transform(texts[te])
        e1_te = np.zeros((len(te), len(CATEGORIES)), dtype=np.float32)
        for ci in range(len(CATEGORIES)):
            m = y[tr, ci] >= 0
            yt = y[tr, ci][m]
            if (yt == 1).sum() < 2 or (yt == 0).sum() < 2:
                continue
            e1_te[:, ci] = _fit_lr(Xtr_full[m], yt, Xte_full)
        cand_te = {"rule": rule_pred[te], "e1": e1_te,
                   "rule|e1": np.maximum(rule_pred[te], e1_te)}

        fold_choice = {}
        for ci, cat in enumerate(CATEGORIES):
            m = y[tr, ci] >= 0
            yt = y[tr, ci][m]
            best, best_f1 = "rule", -1.0
            for name, p in cand_inner.items():
                f1 = _f1_binary(yt, p[m, ci])
                if f1 > best_f1:
                    best, best_f1 = name, f1
            fold_choice[cat] = dict(choice=best, inner_f1=round(best_f1, 4))
            oof_e4b[te, ci] = cand_te[best][:, ci]
        choice_log.append(fold_choice)
        print(f"  fold {fold_i + 1}/5 — " +
              ", ".join(f"{c}={v['choice']}" for c, v in fold_choice.items()))

    res_e4b = oof_score(y, oof_e4b)
    res_rule = oof_score(y, rule_pred)
    print(f"\n{'카테고리':<8} {'rule':<26} {'e4b(nested)':<26}")
    print("-" * 62)
    for c in CATEGORIES:
        print(f"{c:<8} {_fmt(res_rule['per_cat'][c]):<26} {_fmt(res_e4b['per_cat'][c]):<26}")
    print("-" * 62)
    print(f"{'TOTAL':<8} {_fmt(res_rule['total']):<26} {_fmt(res_e4b['total']):<26}")
    print("\n참조: 선택적 앙상블 0.551 [0.515,0.588], E1 단독 0.543 [0.511,0.576]")

    Path("outputs/e4b_nested_measure.json").write_text(json.dumps(
        dict(e4b=res_e4b, choices=choice_log,
             protocol="V0' 동일 + nested 3-fold 선택(누수 0)"),
        ensure_ascii=False, indent=2), encoding="utf-8")
    npz["oof_e4b"] = oof_e4b
    np.savez_compressed("outputs/text_boost_oof.npz", **npz)
    print("(산출물 outputs/e4b_nested_measure.json, npz 에 oof_e4b 추가)")


if __name__ == "__main__":
    main()
