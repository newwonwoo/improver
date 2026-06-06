"""V0' — 공정 baseline 측정 (TF '코더', 레인: 측정만).

목적
----
학습모델(evaluate_cv MLP / evaluate_cv_linear)과 **동일한 holdout 잣대**로
'룰 기반 참조값'을 재서, 학습모델이 룰보다 나은지/못한지 판정한다.

동일성 보장(핵심)
------------------
- 동일 표본: engine.slm.torch_brain.collect_torch_data() 의 row 구성을 그대로
  재현(같은 (law, article) 행, 같은 multi-label y, -1 마스크 동일).
- 동일 fold: StratifiedKFold(k=5, shuffle=True, random_state=42),
  strat 키 = '행에 양성(==1) 라벨이 하나라도 있으면 1' (evaluate_cv 와 동일).
- 동일 micro-F1 + 동일 bootstrap CI(n_boot=1000, seed=42, 행 단위 resample,
  2.5/97.5 percentile) — evaluate_cv 의 f1_*_from_indices / boot_ci 그대로 차용.
- **평가는 test fold 인덱스에서만 집계**(out-of-fold). 룰은 학습이 아니므로
  train 에 fit 할 것이 없어 전체 row 에 적용하되, 각 row 는 그 row 가 test 였던
  fold 에서만 OOF 버퍼에 기록된다(in-sample 함정 회피, 모델과 동일 노출).

레인 준수: 모델/룰/데이터 수정·저장 없음. 측정만.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

from engine.parser import parse_law
from engine.rules import run_all
from engine.slm import ensemble_analyze
from engine.slm.brain import CATEGORIES
from engine.slm.learn import RULE_CAT, REASONING_RULE_CAT
from engine.slm.torch_brain import _prf


def _norm(s: str) -> str:
    return s.replace(" ", "").strip() if s else ""


def build_rows_and_rule_preds():
    """collect_torch_data 와 동일한 row 구성 + 같은 행 정렬로
    (y, rule_pred, ens_pred) 행렬 생성.

    반환
        keys      : list[(law, article)]  — row 순서(collect_torch_data 와 동일 생성 순서)
        y         : (n, 5)  라벨 (-1=결측)  — collect_torch_data 와 동일
        rule_pred : (n, 5)  룰 단독 예측(0/1) — (cat, article) 룰 발화 여부
        ens_pred  : (n, 5)  룰+SLM 앙상블 예측(0/1) — ensemble_analyze fire 여부
    """
    with open("outputs/verification_dataset.jsonl") as f:
        rows = [json.loads(l) for l in f]
    fid_map = json.loads(Path("outputs/fid_article_map.json").read_text(encoding="utf-8"))

    # ── collect_torch_data 의 row 키 구성 그대로 재현 ──
    art_labels: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
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
        rule_id = r["rule_id"]
        cat = RULE_CAT.get(rule_id) or REASONING_RULE_CAT.get(rule_id)
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
        label = 1 if r["verdict"] == "TP" else 0
        prev = art_labels[key].get(cat)
        if prev is None or label > prev:
            art_labels[key][cat] = label

    keys = art_keys_order
    n = len(keys)
    y = np.full((n, len(CATEGORIES)), -1.0, dtype=np.float32)
    for ri, key in enumerate(keys):
        for ci, c in enumerate(CATEGORIES):
            v = art_labels[key].get(c)
            if v is not None:
                y[ri, ci] = float(v)

    # ── 룰 단독 + 앙상블 예측: 법별 1회 실행, (cat, article) fire 인덱스 ──
    key_index = {k: i for i, k in enumerate(keys)}
    rule_pred = np.zeros((n, len(CATEGORIES)), dtype=np.float32)
    ens_pred = np.zeros((n, len(CATEGORIES)), dtype=np.float32)
    cat_idx = {c: i for i, c in enumerate(CATEGORIES)}

    laws_needed = sorted({k[0] for k in keys})
    for ln in laws_needed:
        law = get_law(ln)
        if law is None:
            continue
        findings = run_all(law)

        # (A) 룰 단독: finding 발화 → (cat, norm(article)) 집합
        rule_fire: set[tuple[str, str]] = set()
        for fnd in findings:
            cat = RULE_CAT.get(fnd.pattern_id) or REASONING_RULE_CAT.get(fnd.pattern_id)
            if not cat:
                continue
            rule_fire.add((cat, _norm(fnd.article_number)))

        # (B) 룰+SLM 앙상블: 누수 없는 평가 위해 backend="linear"
        #     (torch 모델은 같은 데이터로 학습된 프로덕션 가중치라 in-sample 누수)
        ens = ensemble_analyze(law, findings, backend="linear")
        ens_fire: set[tuple[str, str]] = set()
        for cat, vlist in ens.items():
            for v in vlist:
                ens_fire.add((cat, _norm(v.article_number)))

        # 이 법에 속한 평가 row 에만 매핑
        for ci, c in enumerate(CATEGORIES):
            for k in keys:
                if k[0] != ln:
                    continue
                ri = key_index[k]
                an_norm = _norm(k[1])
                if (c, an_norm) in rule_fire:
                    rule_pred[ri, ci] = 1.0
                if (c, an_norm) in ens_fire:
                    ens_pred[ri, ci] = 1.0

    return keys, y, rule_pred, ens_pred


def oof_score(y, pred, *, k=5, seed=42, n_boot=1000, n_pos_min=15):
    """evaluate_cv 와 동일한 fold 분할 + test-fold-only OOF + 동일 bootstrap CI.

    pred 는 미리 계산된 0/1 예측(룰은 fold 무관 → 어느 fold 든 동일)이지만,
    OOF 버퍼에는 각 row 가 그 row 의 test fold 에서만 기록된다(모델과 동일 노출).
    """
    from sklearn.model_selection import StratifiedKFold, KFold

    n = y.shape[0]
    strat = ((y == 1).any(axis=1)).astype(int)
    n_pos_rows = int(strat.sum())
    if n_pos_rows >= k and n_pos_rows <= n - k:
        splitter = StratifiedKFold(n_splits=k, shuffle=True, random_state=seed)
        split_iter = splitter.split(np.zeros(n), strat)
        strat_mode = f"StratifiedKFold(양성보유행 {n_pos_rows}/{n} 근사)"
    else:
        splitter = KFold(n_splits=k, shuffle=True, random_state=seed)
        split_iter = splitter.split(np.zeros(n))
        strat_mode = f"KFold(양성보유행 {n_pos_rows} 부족 폴백)"

    oof_pred = np.full((n, len(CATEGORIES)), np.nan, dtype=np.float32)
    oof_y = np.full((n, len(CATEGORIES)), -1.0, dtype=np.float32)
    for train_idx, test_idx in split_iter:
        # 룰은 train 에 fit 할 것 없음 → test fold 인덱스에서만 예측 기록(OOF)
        oof_pred[test_idx] = pred[test_idx]
        oof_y[test_idx] = y[test_idx]

    # ── 동일 micro-F1 + bootstrap CI (evaluate_cv 와 동일 로직) ──
    rng = np.random.default_rng(seed)

    def f1_from_indices(idx, col):
        yt = oof_y[idx, col]
        m = yt >= 0
        yt = yt[m]
        yp = (oof_pred[idx, col][m] >= 0.5).astype(float)
        tp = float(((yp == 1) & (yt == 1)).sum())
        fp = float(((yp == 1) & (yt == 0)).sum())
        fn = float(((yp == 0) & (yt == 1)).sum())
        _, _, f1 = _prf(tp, fp, fn)
        return f1

    def f1_total_from_indices(idx):
        tp = fp = fn = 0.0
        for col in range(len(CATEGORIES)):
            yt = oof_y[idx, col]
            m = yt >= 0
            yt = yt[m]
            yp = (oof_pred[idx, col][m] >= 0.5).astype(float)
            tp += float(((yp == 1) & (yt == 1)).sum())
            fp += float(((yp == 1) & (yt == 0)).sum())
            fn += float(((yp == 0) & (yt == 1)).sum())
        _, _, f1 = _prf(tp, fp, fn)
        return f1

    all_idx = np.arange(n)

    def boot_ci(point_fn):
        stats = np.empty(n_boot, dtype=np.float64)
        for b in range(n_boot):
            samp = rng.integers(0, n, size=n)
            stats[b] = point_fn(samp)
        lo, hi = np.percentile(stats, [2.5, 97.5])
        return float(lo), float(hi)

    per_cat = {}
    for ci, cat in enumerate(CATEGORIES):
        n_pos = int((oof_y[:, ci] == 1).sum())
        f1_point = f1_from_indices(all_idx, ci)
        if n_pos < n_pos_min:
            lo = hi = float("nan")
        else:
            lo, hi = boot_ci(lambda idx, _c=ci: f1_from_indices(idx, _c))
        per_cat[cat] = dict(n_pos=n_pos, f1=f1_point, ci_lo=lo, ci_hi=hi,
                            measurable=(n_pos >= n_pos_min))

    total_n_pos = int((oof_y == 1).sum())
    total_f1 = f1_total_from_indices(all_idx)
    total_lo, total_hi = boot_ci(f1_total_from_indices)
    total = dict(n_pos=total_n_pos, f1=total_f1, ci_lo=total_lo, ci_hi=total_hi)
    return dict(per_cat=per_cat, total=total, strat_mode=strat_mode, n=n)


def _fmt(d):
    if d.get("measurable", True) and not np.isnan(d["ci_lo"]):
        return f"{d['f1']:.3f} [{d['ci_lo']:.3f},{d['ci_hi']:.3f}]"
    return f"{d['f1']:.3f} [측정불가 n_pos<15]"


def main():
    print("[V0'] 공정 baseline 측정 — 동일 holdout(StratifiedKFold k=5 seed=42, "
          "micro-F1, bootstrap CI n_boot=1000)\n")
    keys, y, rule_pred, ens_pred = build_rows_and_rule_preds()
    print(f"N rows={len(keys)}  (collect_torch_data 와 동일 표본)\n")

    A = oof_score(y, rule_pred)
    B = oof_score(y, ens_pred)
    print("strat_mode:", A["strat_mode"], "\n")

    # 학습모델 참조(팀장 제공): MLP 0.508, 선형 0.480 — 같은 CV 로 재산출도 가능
    cats = list(CATEGORIES)
    print(f"{'카테고리':<8} {'n_pos':>5}  {'(A)룰단독':<24} {'(B)룰+SLM(linear)':<24}")
    print("-" * 70)
    for c in cats:
        a = A["per_cat"][c]; b = B["per_cat"][c]
        print(f"{c:<8} {a['n_pos']:>5}  {_fmt(a):<24} {_fmt(b):<24}")
    print("-" * 70)
    print(f"{'TOTAL':<8} {A['total']['n_pos']:>5}  "
          f"{_fmt(A['total']):<24} {_fmt(B['total']):<24}")

    out = dict(rule_only=A, rule_slm=B, n=len(keys))
    Path("outputs/v0prime_fair_baseline.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n(측정 산출물 outputs/v0prime_fair_baseline.json 기록 — 모델/룰/데이터 미수정)")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    main()
