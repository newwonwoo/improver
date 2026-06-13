"""강화 실험 v2 — rule_id 신호 + 강한 모델로 70 도달 가능성 측정.

발견: rule_id 의 TP율 편차가 큼(S-01/S-02=0%, L-03=1% … E-03=50%).
지금 모델은 rule_id 를 안 씀 → 특징으로 추가하면 오탐 대량 제거 기대.
(추론 시 어떤 룰이 걸렸는지는 알려진 정보이므로 누수 아님.)

조합: 구조특징 + rule_id one-hot + 텍스트 TF-IDF.
모델: LogReg / HistGradientBoosting. 5-fold OOF, best-F1 + 고정임계(0.5) F1.
LLM 0회.
"""
from __future__ import annotations

import json
import sys
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")

from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD
from sklearn.pipeline import Pipeline

from engine.parser import parse_law
from engine.slm.features import extract_features
from engine.slm.learn import RULE_CAT

CATEGORIES = ["구조", "공정성", "적법성", "거버넌스", "효율성"]


def collect():
    rows = [json.loads(l) for l in open("outputs/verification_dataset.jsonl")]
    fid_map = json.loads(Path("outputs/fid_article_map.json").read_text(encoding="utf-8"))
    law_cache: dict = {}

    def get_law(name):
        if name in law_cache:
            return law_cache[name]
        md = Path(f"data/laws/raw/{name}/법률.md")
        if not md.exists():
            law_cache[name] = None; return None
        t = md.read_text(encoding="utf-8", errors="replace")
        if t.lstrip().startswith("---"):
            p = t.split("---", 2)
            if len(p) >= 3: t = p[2]
        try:
            law = parse_law(t, name=name); law_cache[name] = law; return law
        except Exception:
            law_cache[name] = None; return None

    per_cat = defaultdict(lambda: {"struct": [], "text": [], "rule": [], "y": []})
    for r in rows:
        if r["verdict"] not in ("TP", "FP"):
            continue
        cat = RULE_CAT.get(r["rule_id"])
        if not cat or "@" not in r["fid"]:
            continue
        _, name = r["fid"].split("@", 1)
        an = fid_map.get(r["fid"])
        if not an:
            continue
        law = get_law(name)
        if law is None:
            continue
        art = next((a for a in law.articles
                    if a.number.replace(" ", "") == an.replace(" ", "")), None)
        if not art:
            continue
        per_cat[cat]["struct"].append(extract_features(art).to_dict())
        per_cat[cat]["text"].append(art.full_text or "")
        per_cat[cat]["rule"].append(r["rule_id"])
        per_cat[cat]["y"].append(1 if r["verdict"] == "TP" else 0)
    return per_cat


def best_f1(y, proba):
    best = (0.0, 0.5)
    for t in np.linspace(0.05, 0.95, 19):
        pred = (proba >= t).astype(int)
        tp = int(((pred == 1) & (y == 1)).sum())
        fp = int(((pred == 1) & (y == 0)).sum())
        fn = int(((pred == 0) & (y == 1)).sum())
        p = tp / max(tp + fp, 1); r = tp / max(tp + fn, 1)
        f1 = 2 * p * r / max(p + r, 1e-9)
        if f1 > best[0]:
            best = (f1, t)
    return best


def f1_at(y, proba, t):
    pred = (proba >= t).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    p = tp / max(tp + fp, 1); r = tp / max(tp + fn, 1)
    return 2 * p * r / max(p + r, 1e-9)


def build_X(d, rule_vocab, feat, svd_text=None, fit_text=None):
    """구조 + rule one-hot (+ 텍스트 SVD) 결합 행렬."""
    Xs = np.array([[s.get(k, 0.0) for k in feat] for s in d["struct"]])
    R = np.zeros((len(d["y"]), len(rule_vocab)))
    for i, rid in enumerate(d["rule"]):
        if rid in rule_vocab:
            R[i, rule_vocab[rid]] = 1.0
    parts = [Xs, R]
    return np.hstack(parts)


def run():
    per_cat = collect()
    print(f"{'cat':<8}{'n':>6}{'tp':>5}  {'LR+rule':>9}{'GB+rule':>9}{'GB+txt':>9}")
    print("-" * 50)
    rows_out = {}
    hybrid_num = hybrid_den = 0.0
    for cat in CATEGORIES:
        d = per_cat[cat]
        y = np.array(d["y"])
        n, tp = len(y), int(y.sum())
        if n < 40 or tp < 8:
            print(f"{cat:<8}{n:>6}{tp:>5}  (skip)")
            continue
        feat = list(d["struct"][0].keys())
        rule_vocab = {r: i for i, r in enumerate(sorted(set(d["rule"])))}
        Xsr = build_X(d, rule_vocab, feat)
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

        # 모델 A: LogReg on struct+rule
        oofA = np.zeros(n)
        # 모델 B: HistGB on struct+rule
        oofB = np.zeros(n)
        # 모델 C: HistGB on struct+rule+text(SVD)
        oofC = np.zeros(n)
        for tr, va in skf.split(Xsr, y):
            sc = StandardScaler().fit(Xsr[tr])
            a = LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced")
            a.fit(sc.transform(Xsr[tr]), y[tr])
            oofA[va] = a.predict_proba(sc.transform(Xsr[va]))[:, 1]

            b = HistGradientBoostingClassifier(max_depth=3, max_iter=200,
                                               learning_rate=0.08, l2_regularization=1.0,
                                               class_weight="balanced", random_state=42)
            b.fit(Xsr[tr], y[tr])
            oofB[va] = b.predict_proba(Xsr[va])[:, 1]

            # 텍스트 SVD (폴드 내부 적합)
            tf = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4),
                                 max_features=3000, min_df=2)
            Ttr = tf.fit_transform([d["text"][i] for i in tr])
            k = min(50, Ttr.shape[1] - 1, len(tr) - 1)
            svd = TruncatedSVD(n_components=max(2, k), random_state=42).fit(Ttr)
            Ttr_s = svd.transform(Ttr)
            Tva_s = svd.transform(tf.transform([d["text"][i] for i in va]))
            Xc_tr = np.hstack([Xsr[tr], Ttr_s])
            Xc_va = np.hstack([Xsr[va], Tva_s])
            c = HistGradientBoostingClassifier(max_depth=3, max_iter=200,
                                               learning_rate=0.08, l2_regularization=1.0,
                                               class_weight="balanced", random_state=42)
            c.fit(Xc_tr, y[tr])
            oofC[va] = c.predict_proba(Xc_va)[:, 1]

        fA, _ = best_f1(y, oofA)
        fB, _ = best_f1(y, oofB)
        fC, _ = best_f1(y, oofC)
        print(f"{cat:<8}{n:>6}{tp:>5}  {fA:>9.3f}{fB:>9.3f}{fC:>9.3f}")
        bestf = max(fA, fB, fC)
        rows_out[cat] = dict(n=n, tp=tp, lr_rule=fA, gb_rule=fB, gb_text=fC, best=bestf)
        hybrid_num += bestf * n; hybrid_den += n

    print("-" * 50)
    if hybrid_den:
        print(f"{'HYBRID(best/cat) 가중 F1':<30} = {hybrid_num/hybrid_den:.3f}")
    Path("outputs/slm_stack_experiment_v2.json").write_text(
        json.dumps(rows_out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("저장: outputs/slm_stack_experiment_v2.json")


if __name__ == "__main__":
    run()
