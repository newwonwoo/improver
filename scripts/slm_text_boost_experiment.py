"""E1~E4 — 텍스트(char n-gram TF-IDF)·부스팅 추론능력 강화 실험.

계획: docs/PLAN_REASONING_REINFORCEMENT_v2.md §2
프로토콜(감사인 게이트 §3): V0' 동일 잣대 — 같은 행 구성, 같은
StratifiedKFold(k=5, seed=42), 같은 micro-F1 + bootstrap CI(1,000회).
TF-IDF·스케일러·모델·게이팅 선택 전부 train fold 에서만 fit/결정,
집계는 OOF(test fold) 예측만. LLM·외부 API 0회.

실험
----
E1  char n-gram TF-IDF(2~4) → 카테고리별 LogisticRegression(balanced)
E2  정량 dense(+cat 인덱스) → HistGradientBoostingClassifier
E3  TF-IDF ⊕ 표준화 dense 결합 → LogisticRegression
E4  카테고리별 선택 게이팅: {룰, E1, E2, E3, 룰∨E1, 룰∨E2, 룰∨E3} 중
    train-fold F1 최고를 선택(선택도 fold 내부 — 누수 없음. 단 학습모델의
    train F1 은 in-sample 이라 선택이 과적합 후보로 기울 수 있음 — 이는
    선택 품질 문제일 뿐 test 추정치는 OOF 로 정직함)

레인 준수: 측정만. 모델/룰/config 미수정.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np

import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_sys.path.insert(0, _ROOT)
_sys.path.insert(0, _os.path.join(_ROOT, "scripts"))

from engine.parser import parse_law
from engine.rules import run_all
from engine.slm.brain import CATEGORIES
from engine.slm.learn import RULE_CAT, REASONING_RULE_CAT
from engine.slm.torch_brain import _extract_dense_and_cat, _prf

from v0prime_fair_rule_baseline import oof_score, _fmt, _norm


def build_rows():
    """V0' build_rows_and_rule_preds 와 동일한 row 구성 + 텍스트·dense 피처.

    반환: keys, y(n,5; -1결측), rule_pred(n,5), texts(n,), dense(n,d)
    """
    with open("outputs/verification_dataset.jsonl") as f:
        rows = [json.loads(l) for l in f]
    fid_map = json.loads(Path("outputs/fid_article_map.json").read_text(encoding="utf-8"))

    art_labels: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    art_objects: dict[tuple[str, str], object] = {}
    art_keys_order: list[tuple[str, str]] = []
    seen = set()
    law_cache: dict[str, object] = {}

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
        cat = RULE_CAT.get(r["rule_id"]) or REASONING_RULE_CAT.get(r["rule_id"])
        if not cat:
            continue
        fid = r["fid"]
        if "@" not in fid:
            continue
        _, ln = fid.split("@", 1)
        an = fid_map.get(fid)
        if not an:
            continue
        law = get_law(ln)
        if law is None:
            continue
        art = next((a for a in law.articles
                    if a.number.replace(" ", "") == an.replace(" ", "")), None)
        if not art:
            continue
        key = (ln, an)
        if key not in seen:
            seen.add(key)
            art_keys_order.append(key)
            art_objects[key] = art
        label = 1 if r["verdict"] == "TP" else 0
        prev = art_labels[key].get(cat)
        if prev is None or label > prev:
            art_labels[key][cat] = label

    keys = art_keys_order
    n = len(keys)
    y = np.full((n, len(CATEGORIES)), -1.0, dtype=np.float32)
    texts: list[str] = []
    dense_list = []
    for ri, key in enumerate(keys):
        for ci, c in enumerate(CATEGORIES):
            v = art_labels[key].get(c)
            if v is not None:
                y[ri, ci] = float(v)
        art = art_objects[key]
        texts.append(art.full_text or "")
        d, ti, si, mi = _extract_dense_and_cat(art)
        # 트리 모델용: cat 인덱스를 숫자 그대로 부가 (분기 학습 가능)
        dense_list.append(list(d) + [float(ti), float(si), float(mi)])
    dense = np.array(dense_list, dtype=np.float32)

    # 룰 단독 예측 (V0' 와 동일 방식)
    key_index = {k: i for i, k in enumerate(keys)}
    rule_pred = np.zeros((n, len(CATEGORIES)), dtype=np.float32)
    for ln in sorted({k[0] for k in keys}):
        law = get_law(ln)
        if law is None:
            continue
        rule_fire: set[tuple[str, str]] = set()
        for fnd in run_all(law):
            cat = RULE_CAT.get(fnd.pattern_id) or REASONING_RULE_CAT.get(fnd.pattern_id)
            if cat:
                rule_fire.add((cat, _norm(fnd.article_number)))
        for k in keys:
            if k[0] != ln:
                continue
            ri = key_index[k]
            an_norm = _norm(k[1])
            for ci, c in enumerate(CATEGORIES):
                if (c, an_norm) in rule_fire:
                    rule_pred[ri, ci] = 1.0
    return keys, y, rule_pred, np.array(texts, dtype=object), dense


def fold_splits(y, *, k=5, seed=42):
    """oof_score 와 동일한 fold 분할 (같은 seed·strat 키 → 동일 split 재현)."""
    from sklearn.model_selection import StratifiedKFold, KFold
    n = y.shape[0]
    strat = ((y == 1).any(axis=1)).astype(int)
    n_pos_rows = int(strat.sum())
    if n_pos_rows >= k and n_pos_rows <= n - k:
        sp = StratifiedKFold(n_splits=k, shuffle=True, random_state=seed)
        return list(sp.split(np.zeros(n), strat))
    sp = KFold(n_splits=k, shuffle=True, random_state=seed)
    return list(sp.split(np.zeros(n)))


def _f1_binary(yt, yp):
    tp = float(((yp == 1) & (yt == 1)).sum())
    fp = float(((yp == 1) & (yt == 0)).sum())
    fn = float(((yp == 0) & (yt == 1)).sum())
    return _prf(tp, fp, fn)[2]


def _fit_lr_per_cat(Xtr, Xte, y_tr):
    """카테고리별 LR(balanced) 학습 → (test 0/1 예측, train 0/1 예측)."""
    from sklearn.linear_model import LogisticRegression
    n_te = Xte.shape[0]
    n_tr = Xtr.shape[0]
    pred_te = np.zeros((n_te, len(CATEGORIES)), dtype=np.float32)
    pred_tr = np.zeros((n_tr, len(CATEGORIES)), dtype=np.float32)
    for ci in range(len(CATEGORIES)):
        m = y_tr[:, ci] >= 0
        yt = y_tr[m, ci]
        if (yt == 1).sum() < 2 or (yt == 0).sum() < 2:
            continue
        clf = LogisticRegression(max_iter=2000, class_weight="balanced")
        clf.fit(Xtr[m], yt)
        pred_te[:, ci] = (clf.predict_proba(Xte)[:, 1] >= 0.5).astype(np.float32)
        pred_tr[:, ci] = (clf.predict_proba(Xtr)[:, 1] >= 0.5).astype(np.float32)
    return pred_te, pred_tr


def _fit_hgb_per_cat(Xtr, Xte, y_tr):
    from sklearn.ensemble import HistGradientBoostingClassifier
    n_te = Xte.shape[0]
    n_tr = Xtr.shape[0]
    pred_te = np.zeros((n_te, len(CATEGORIES)), dtype=np.float32)
    pred_tr = np.zeros((n_tr, len(CATEGORIES)), dtype=np.float32)
    for ci in range(len(CATEGORIES)):
        m = y_tr[:, ci] >= 0
        yt = y_tr[m, ci]
        if (yt == 1).sum() < 2 or (yt == 0).sum() < 2:
            continue
        clf = HistGradientBoostingClassifier(
            max_depth=3, max_iter=200, learning_rate=0.1,
            class_weight="balanced", random_state=42)
        clf.fit(Xtr[m], yt)
        pred_te[:, ci] = (clf.predict_proba(Xte)[:, 1] >= 0.5).astype(np.float32)
        pred_tr[:, ci] = (clf.predict_proba(Xtr)[:, 1] >= 0.5).astype(np.float32)
    return pred_te, pred_tr


def main():
    print("[E1~E4] 텍스트·부스팅 강화 실험 — V0' 동일 잣대 (계획 v2 §3)\n")
    keys, y, rule_pred, texts, dense = build_rows()
    n = len(keys)
    print(f"N rows={n}, dense dim={dense.shape[1]}\n")

    splits = fold_splits(y)

    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import StandardScaler
    from scipy.sparse import hstack, csr_matrix

    oof = {name: np.zeros((n, len(CATEGORIES)), dtype=np.float32)
           for name in ("e1_text", "e2_boost", "e3_combo", "e4_select")}
    choice_log: list[dict] = []

    for fold_i, (tr, te) in enumerate(splits):
        # ── train fold 에서만 fit (누수 0) ──
        vec = TfidfVectorizer(analyzer="char", ngram_range=(2, 4),
                              max_features=2000, sublinear_tf=True, min_df=2)
        Ttr = vec.fit_transform(texts[tr])
        Tte = vec.transform(texts[te])

        scaler = StandardScaler().fit(dense[tr])
        Dtr = scaler.transform(dense[tr])
        Dte = scaler.transform(dense[te])

        Ctr = hstack([Ttr, csr_matrix(Dtr)]).tocsr()
        Cte = hstack([Tte, csr_matrix(Dte)]).tocsr()

        y_tr = y[tr]
        e1_te, e1_tr = _fit_lr_per_cat(Ttr, Tte, y_tr)
        e2_te, e2_tr = _fit_hgb_per_cat(dense[tr], dense[te], y_tr)
        e3_te, e3_tr = _fit_lr_per_cat(Ctr, Cte, y_tr)
        oof["e1_text"][te] = e1_te
        oof["e2_boost"][te] = e2_te
        oof["e3_combo"][te] = e3_te

        # ── E4: 카테고리별 후보 선택 — train fold 라벨로만 결정 ──
        rule_tr, rule_te = rule_pred[tr], rule_pred[te]
        cand_tr = {
            "rule": rule_tr, "e1": e1_tr, "e2": e2_tr, "e3": e3_tr,
            "rule|e1": np.maximum(rule_tr, e1_tr),
            "rule|e2": np.maximum(rule_tr, e2_tr),
            "rule|e3": np.maximum(rule_tr, e3_tr),
        }
        cand_te = {
            "rule": rule_te, "e1": e1_te, "e2": e2_te, "e3": e3_te,
            "rule|e1": np.maximum(rule_te, e1_te),
            "rule|e2": np.maximum(rule_te, e2_te),
            "rule|e3": np.maximum(rule_te, e3_te),
        }
        fold_choice = {}
        for ci, cat in enumerate(CATEGORIES):
            m = y_tr[:, ci] >= 0
            yt = y_tr[m, ci]
            best_name, best_f1 = "rule", -1.0
            for name, p in cand_tr.items():
                f1 = _f1_binary(yt, p[m, ci])
                if f1 > best_f1:
                    best_name, best_f1 = name, f1
            fold_choice[cat] = dict(choice=best_name, train_f1=round(best_f1, 4))
            oof["e4_select"][te, ci] = cand_te[best_name][:, ci]
        choice_log.append(fold_choice)
        print(f"  fold {fold_i + 1}/5 완료 — E4 선택: "
              + ", ".join(f"{c}={v['choice']}" for c, v in fold_choice.items()))

    # ── 채점: V0' oof_score 그대로 (동일 fold 재현 → OOF 기록 동일) ──
    results = {"rule_only": oof_score(y, rule_pred)}
    for name, pred in oof.items():
        results[name] = oof_score(y, pred)

    cats = list(CATEGORIES)
    names = ["rule_only", "e1_text", "e2_boost", "e3_combo", "e4_select"]
    print(f"\n{'카테고리':<8}" + "".join(f" {nm:<26}" for nm in names))
    print("-" * (8 + 27 * len(names)))
    for c in cats:
        print(f"{c:<8}" + "".join(f" {_fmt(results[nm]['per_cat'][c]):<26}" for nm in names))
    print("-" * (8 + 27 * len(names)))
    print(f"{'TOTAL':<8}" + "".join(f" {_fmt(results[nm]['total']):<26}" for nm in names))

    print("\n참조(기측정): 선택적 앙상블 total F1=0.551 [0.515, 0.588] "
          "(outputs/selective_ensemble_measure.json)")

    out = dict(results=results, e4_choices=choice_log, n=n,
               protocol="V0' 동일(StratifiedKFold k=5 seed=42, micro-F1, boot CI 1000)")
    Path("outputs/text_boost_measure.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # LLM 벤치마크용 동일 표본 자산 (행 정렬 보존; texts 는 용량상 git 제외)
    np.savez_compressed(
        "outputs/text_boost_oof.npz", y=y, rule_pred=rule_pred,
        **{f"oof_{k}": v for k, v in oof.items()})
    with open("outputs/text_boost_rows.jsonl", "w", encoding="utf-8") as f:
        for i, (ln, an) in enumerate(keys):
            f.write(json.dumps(dict(i=i, law=ln, article=an, text=str(texts[i])),
                               ensure_ascii=False) + "\n")
    print("\n(측정 산출물 outputs/text_boost_measure.json + OOF 행렬/행 텍스트 — "
          "모델/룰/config 미수정)")


if __name__ == "__main__":
    main()
