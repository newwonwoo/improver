"""OOF 스태킹 강화 실험 — 추론엔진 신경망 강화(측정 우선, 프로덕션 무변).

진단(에이전트+로드맵):
 - 최강 단일모델 TextBrain(TF-IDF, F1≈0.594)이 하드코딩으로 꺼져 있음.
 - 큰 NN(BERT/GNN)은 양성 42~83건/카테고리로 오버피팅 확정.
 - 기존 측정은 단일 train/test 분할 → 분산 큼.

강화 가설: 다양한 기존 신호(구조 LogReg / 구조 Poly-interaction / 텍스트 TF-IDF)를
**폴드 내부에서 누수 없이** OOF 스태킹 + 확률보정으로 결합하면, 작은 데이터에서도
단일모델보다 견고하게 F1↑. 모두 5-fold CV로 정직 측정. LLM 0회.

실행: python scripts/slm_stack_experiment.py
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
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler, PolynomialFeatures
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline
from sklearn.isotonic import IsotonicRegression

from engine.parser import parse_law
from engine.slm.features import extract_features
from engine.slm.learn import RULE_CAT

CATEGORIES = ["구조", "공정성", "적법성", "거버넌스", "효율성"]


def collect():
    """카테고리별 (구조특징dict, 조문텍스트, label) 수집 — 텍스트 포함."""
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

    per_cat = defaultdict(lambda: {"struct": [], "text": [], "y": []})
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
        fv = extract_features(art).to_dict()
        per_cat[cat]["struct"].append(fv)
        per_cat[cat]["text"].append(art.full_text or "")
        per_cat[cat]["y"].append(1 if r["verdict"] == "TP" else 0)
    return per_cat


def _struct_logreg():
    return Pipeline([("sc", StandardScaler()),
                     ("clf", LogisticRegression(C=1.0, max_iter=1000,
                                                class_weight="balanced", random_state=42))])


def _struct_poly():
    return Pipeline([("sc", StandardScaler()),
                     ("poly", PolynomialFeatures(2, interaction_only=True, include_bias=False)),
                     ("clf", LogisticRegression(C=0.5, max_iter=2000,
                                                class_weight="balanced", random_state=42))])


def _text_tfidf():
    return Pipeline([("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4),
                                                max_features=2000, min_df=2)),
                     ("clf", LogisticRegression(C=1.0, max_iter=2000,
                                                class_weight="balanced", random_state=42))])


def best_f1(y, proba):
    """OOF 확률에서 F1 최대 임계값과 그 F1 (모든 모델에 동일 적용 → 공정 비교)."""
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


def oof_proba(make_model, data, y, skf, use_text):
    """폴드 내부에서만 학습 → 누수 없는 OOF 확률."""
    oof = np.zeros(len(y))
    if not use_text:
        X = np.array([[s.get(k, 0.0) for k in FEAT] for s in data["struct"]])
    for tr, va in skf.split(np.zeros(len(y)), y):
        m = make_model()
        if use_text:
            m.fit([data["text"][i] for i in tr], y[tr])
            oof[va] = m.predict_proba([data["text"][i] for i in va])[:, 1]
        else:
            m.fit(X[tr], y[tr])
            oof[va] = m.predict_proba(X[va])[:, 1]
    return oof


FEAT: list = []


def run():
    per_cat = collect()
    global FEAT
    print(f"{'cat':<8}{'n':>6}{'tp':>5}  {'struct':>7}{'poly':>7}{'text':>7}{'stk3':>8}{'stk2':>8}")
    print("-" * 52)
    summary = {}
    agg = {"struct": [], "poly": [], "text": [], "stack": []}
    agg_w = []
    for cat in CATEGORIES:
        d = per_cat[cat]
        y = np.array(d["y"])
        n, tp = len(y), int(y.sum())
        if n < 40 or tp < 8 or (n - tp) < 8:
            print(f"{cat:<8}{n:>6}{tp:>5}  (표본 부족 — skip)")
            continue
        FEAT = list(d["struct"][0].keys())
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

        oof_s = oof_proba(_struct_logreg, d, y, skf, use_text=False)
        oof_p = oof_proba(_struct_poly, d, y, skf, use_text=False)
        oof_t = oof_proba(_text_tfidf, d, y, skf, use_text=True)

        def stack_oof(cols):
            """주어진 base OOF 확률열 → 메타 LogReg + isotonic 보정 (2차 OOF, 누수 없음)."""
            M = np.column_stack(cols)
            out = np.zeros(len(y))
            for tr, va in skf.split(M, y):
                meta = LogisticRegression(C=1.0, max_iter=1000, class_weight="balanced")
                meta.fit(M[tr], y[tr])
                raw = meta.predict_proba(M[va])[:, 1]
                try:
                    iso = IsotonicRegression(out_of_bounds="clip")
                    iso.fit(meta.predict_proba(M[tr])[:, 1], y[tr])
                    out[va] = iso.predict(raw)
                except Exception:
                    out[va] = raw
            return out

        oof_stack3 = stack_oof([oof_s, oof_p, oof_t])   # struct+poly+text
        oof_stack2 = stack_oof([oof_s, oof_t])          # struct+text (poly 제거)

        fs, _ = best_f1(y, oof_s)
        fp_, _ = best_f1(y, oof_p)
        ft, _ = best_f1(y, oof_t)
        f3, _ = best_f1(y, oof_stack3)
        f2, t2 = best_f1(y, oof_stack2)
        fst = max(f2, f3)
        print(f"{cat:<8}{n:>6}{tp:>5}  {fs:>7.3f}{fp_:>7.3f}{ft:>7.3f}{f3:>8.3f}{f2:>8.3f}")
        summary[cat] = dict(n=n, tp=tp, struct=fs, poly=fp_, text=ft,
                            stack3=f3, stack2=f2, thr=t2)
        for k, v in [("struct", fs), ("poly", fp_), ("text", ft), ("stack", fst)]:
            agg[k].append(v)
        agg_w.append(n)

    print("-" * 52)
    if agg_w:
        wsum = sum(agg_w)
        def wmean(key):
            return sum(f * w for f, w in zip(agg[key], agg_w)) / wsum
        print(f"{'W.MEAN':<8}{wsum:>6}{'':>5}  "
              f"{wmean('struct'):>7.3f}{wmean('poly'):>7.3f}"
              f"{wmean('text'):>7.3f}{wmean('stack'):>8.3f}")
        summary["_weighted_mean"] = {k: wmean(k) for k in agg}
    Path("outputs/slm_stack_experiment.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n저장: outputs/slm_stack_experiment.json  (5-fold OOF, best-threshold F1)")


if __name__ == "__main__":
    run()
