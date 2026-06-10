"""라운드2 — 측정된 E1 텍스트 강화를 프로덕션 자산으로 학습·저장.

라운드1 측정(outputs/text_boost_measure.json, e4b_nested_measure.json):
char n-gram TF-IDF + 카테고리별 LR 이 정량신호 한계를 돌파(E4b 0.594 > 기존 0.551).
이 함수는 그 모델을 **전체 데이터로 학습해 디스크에 저장**한다(추론 시 재현용).

감사인 게이트:
- 회귀 0: 엔진 기존 경로(ensemble_analyze)는 건드리지 않는다. 본 자산은
  TextBrain 으로 분리 저장되며, 활성화는 기본 OFF(게이트된 결정).
- 누수 0: 저장 모델은 '프로덕션 추론용'이며, 성능 주장은 라운드1 OOF 측정값만 인용
  (저장 모델 자기평가 금지).
- 재현: 동일 seed·동일 피처 파라미터. 저장 메타에 학습 표본수·카테고리 기록.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np

import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_sys.path.insert(0, _ROOT)

from engine.slm.brain import CATEGORIES

TFIDF_PARAMS = dict(analyzer="char", ngram_range=(2, 4),
                    max_features=2000, sublinear_tf=True, min_df=2)
# 라운드1 nested 선택 결과: 텍스트가 측정상 우세한 카테고리만 활성 후보.
# (공정성은 룰 우세 → 텍스트 비활성. outputs/e4b_nested_measure.json 참조)
TEXT_WIN_CATEGORIES = ("구조", "적법성", "효율성", "거버넌스")


def main():
    rows_path = Path("outputs/text_boost_rows.jsonl")
    if not rows_path.exists():
        print("text_boost_rows.jsonl 없음 — slm_text_boost_experiment.py 먼저 실행")
        return
    rows = [json.loads(l) for l in open(rows_path, encoding="utf-8")]
    texts = np.array([r["text"] for r in rows], dtype=object)
    npz = np.load("outputs/text_boost_oof.npz")
    y = npz["y"]

    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression

    vec = TfidfVectorizer(**TFIDF_PARAMS)
    X = vec.fit_transform(texts)

    models = {}
    meta = {}
    for ci, cat in enumerate(CATEGORIES):
        m = y[:, ci] >= 0
        yt = y[m, ci]
        if (yt == 1).sum() < 5 or (yt == 0).sum() < 5:
            meta[cat] = dict(trained=False, reason="표본 부족")
            continue
        clf = LogisticRegression(max_iter=2000, class_weight="balanced")
        clf.fit(X[m], yt)
        models[cat] = clf
        meta[cat] = dict(trained=True, n_pos=int((yt == 1).sum()),
                         n_neg=int((yt == 0).sum()),
                         text_win=cat in TEXT_WIN_CATEGORIES)

    Path("outputs").mkdir(exist_ok=True)
    with open("outputs/text_brain_models.pkl", "wb") as f:
        pickle.dump(dict(vectorizer=vec, models=models,
                         categories=list(CATEGORIES),
                         text_win=list(TEXT_WIN_CATEGORIES),
                         tfidf_params=TFIDF_PARAMS), f)
    Path("outputs/text_brain_meta.json").write_text(json.dumps(
        dict(meta=meta, n_rows=len(rows),
             measured_f1_round1="E1 0.543[0.511,0.576], E4b 0.594[0.562,0.629] (OOF)",
             note="활성화 기본 OFF — 회귀 0. 성능은 라운드1 OOF 측정 인용(자기평가 금지)."),
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: outputs/text_brain_models.pkl ({len(models)}개 카테고리 모델)")
    for cat, mt in meta.items():
        print(f"  {cat}: {mt}")


if __name__ == "__main__":
    main()
