"""V2 다음 단계 — '카테고리 선택적 앙상블' 측정만 (TF '코더', 레인: 측정만).

목적
----
카테고리마다 더 나은 소스(룰단독 vs 룰+SLM 앙상블)를 골라 composite 예측을
구성하면 현재 최고(룰+SLM TOTAL 0.537)를 넘는가? 를 **동일 holdout 잣대**로 측정.

누수 금지(핵심)
---------------
- 소스 선택은 **train fold** 에서만 결정(카테고리별 룰단독 F1 vs 앙상블 F1 비교).
- 그 선택을 **test fold** 에 적용해 OOF 버퍼에 기록 → test-fold-only out-of-fold.
- test fold 로 소스를 고르면 누수/치팅 → 절대 금지.

동일성 보장
-----------
- 동일 표본/라벨/룰·앙상블 예측: v0prime_fair_baseline.build_rows_and_rule_preds() 재사용.
- 동일 fold: StratifiedKFold(k=5, shuffle=True, random_state=42), strat 키 동일.
- 동일 micro-F1 + 동일 bootstrap CI(n_boot=1000, seed=42, 2.5/97.5 pct).
  → v0prime_fair_baseline.oof_score 의 집계 로직 그대로 차용.

레인 준수: 프로덕션 모델/룰/ensemble_analyze 수정·저장 없음. 측정만.
"""
from __future__ import annotations

# ── 경로설정 (top) ──
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import json
from pathlib import Path

import numpy as np

# 기존 v0prime baseline import 재사용 (프로덕션 미수정)
from scripts.v0prime_fair_rule_baseline import build_rows_and_rule_preds, oof_score
from engine.slm.brain import CATEGORIES
from engine.slm.torch_brain import _prf


def _f1_col(oof_y, oof_pred, idx, col):
    """단일 카테고리(col) micro-F1, idx 범위 내, -1 마스크 적용."""
    yt = oof_y[idx, col]
    m = yt >= 0
    yt = yt[m]
    yp = (oof_pred[idx, col][m] >= 0.5).astype(float)
    tp = float(((yp == 1) & (yt == 1)).sum())
    fp = float(((yp == 1) & (yt == 0)).sum())
    fn = float(((yp == 0) & (yt == 1)).sum())
    _, _, f1 = _prf(tp, fp, fn)
    return f1


def _f1_total(oof_y, oof_pred, idx):
    """전체(모든 카테고리 합산) micro-F1, idx 범위 내."""
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


def _f1_train_col(y, pred, idx, col):
    """train fold 내 단일 카테고리 micro-F1 (소스 선택용). -1 마스크 적용."""
    yt = y[idx, col]
    m = yt >= 0
    yt = yt[m]
    yp = (pred[idx, col][m] >= 0.5).astype(float)
    tp = float(((yp == 1) & (yt == 1)).sum())
    fp = float(((yp == 1) & (yt == 0)).sum())
    fn = float(((yp == 0) & (yt == 1)).sum())
    _, _, f1 = _prf(tp, fp, fn)
    return f1


def selective_oof(y, rule_pred, ens_pred, *, k=5, seed=42, n_boot=1000, n_pos_min=15):
    """fold 마다 train 에서 카테고리별 소스 선택 → test 에 적용 → OOF 집계.

    반환: dict(per_cat, total, strat_mode, n, choices)
      choices[cat] = {"rule": cnt, "ens": cnt}  (fold 들에서 선택 빈도)
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

    # 카테고리별 fold 선택 빈도 + 상세 로그
    choices = {c: {"rule": 0, "ens": 0} for c in CATEGORIES}
    fold_detail = []  # 각 fold 의 카테고리별 (train_rule_f1, train_ens_f1, choice)

    for fold_i, (train_idx, test_idx) in enumerate(split_iter):
        fd = {}
        for ci, cat in enumerate(CATEGORIES):
            # ── 소스 선택: train fold 에서만 결정 (누수 금지) ──
            tr_rule_f1 = _f1_train_col(y, rule_pred, train_idx, ci)
            tr_ens_f1 = _f1_train_col(y, ens_pred, train_idx, ci)
            # train 에서 앙상블 F1 이 룰단독보다 엄밀히 크면 앙상블, 동률/이하면 룰단독.
            # (동률 시 룰단독 = 더 단순/보수적 소스 선호 → 타이브레이크 명시)
            use_ens = tr_ens_f1 > tr_rule_f1
            src_pred = ens_pred if use_ens else rule_pred
            choices[cat]["ens" if use_ens else "rule"] += 1
            fd[cat] = dict(train_rule_f1=tr_rule_f1, train_ens_f1=tr_ens_f1,
                           choice=("ens" if use_ens else "rule"))
            # ── test fold 에 그 선택대로 기록 (OOF) ──
            oof_pred[test_idx, ci] = src_pred[test_idx, ci]
            oof_y[test_idx, ci] = y[test_idx, ci]
        fold_detail.append(fd)

    # ── 동일 micro-F1 + bootstrap CI (oof_score 와 동일 로직) ──
    rng = np.random.default_rng(seed)
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
        f1_point = _f1_col(oof_y, oof_pred, all_idx, ci)
        if n_pos < n_pos_min:
            lo = hi = float("nan")
        else:
            lo, hi = boot_ci(lambda idx, _c=ci: _f1_col(oof_y, oof_pred, idx, _c))
        per_cat[cat] = dict(n_pos=n_pos, f1=f1_point, ci_lo=lo, ci_hi=hi,
                            measurable=(n_pos >= n_pos_min))

    total_n_pos = int((oof_y == 1).sum())
    total_f1 = _f1_total(oof_y, oof_pred, all_idx)
    total_lo, total_hi = boot_ci(lambda idx: _f1_total(oof_y, oof_pred, idx))
    total = dict(n_pos=total_n_pos, f1=total_f1, ci_lo=total_lo, ci_hi=total_hi)

    return dict(per_cat=per_cat, total=total, strat_mode=strat_mode, n=n,
                choices=choices, fold_detail=fold_detail)


def _fmt(d):
    if d.get("measurable", True) and not np.isnan(d.get("ci_lo", float("nan"))):
        return f"{d['f1']:.3f} [{d['ci_lo']:.3f},{d['ci_hi']:.3f}]"
    return f"{d['f1']:.3f} [측정불가 n_pos<15]"


def main():
    print("[V2 선택적앙상블] 측정만 — 동일 holdout(StratifiedKFold k=5 seed=42, "
          "micro-F1, bootstrap CI n_boot=1000)\n")
    print("소스 선택은 train fold 에서만 결정 → test fold 적용(누수 금지)\n")

    keys, y, rule_pred, ens_pred = build_rows_and_rule_preds()
    print(f"N rows={len(keys)}  (build_rows_and_rule_preds 재사용, 동일 표본)\n")

    # 동일 잣대로 baseline 재산출(하드코딩 대신 in-process 재계산 → 비교 자기검증)
    A = oof_score(y, rule_pred)   # 룰단독
    B = oof_score(y, ens_pred)    # 룰+SLM 앙상블 (현 프로덕션 최고)
    S = selective_oof(y, rule_pred, ens_pred)
    print("strat_mode:", S["strat_mode"], "\n")

    # ── per-cat 선택적 결과 + fold 선택 빈도 ──
    print(f"{'카테고리':<8} {'n_pos':>5}  {'(S)선택적앙상블':<26} {'fold선택(rule/ens)':<18}")
    print("-" * 74)
    for c in CATEGORIES:
        s = S["per_cat"][c]
        ch = S["choices"][c]
        print(f"{c:<8} {s['n_pos']:>5}  {_fmt(s):<26} "
              f"rule={ch['rule']} / ens={ch['ens']}")
    print("-" * 74)
    print(f"{'TOTAL':<8} {S['total']['n_pos']:>5}  {_fmt(S['total']):<26}")

    # ── fold 별 train 선택 근거 상세 ──
    print("\n[fold 별 train-fold 소스 선택 근거 (train F1: rule vs ens → choice)]")
    for fi, fd in enumerate(S["fold_detail"]):
        print(f" fold{fi}: ", end="")
        parts = []
        for c in CATEGORIES:
            d = fd[c]
            parts.append(f"{c}={d['choice']}(r{d['train_rule_f1']:.2f}/e{d['train_ens_f1']:.2f})")
        print("  ".join(parts))

    # ── per-cat baseline 대비 (선택이 깎인 카테고리 회복했는지 확인용) ──
    print("\n[per-cat 동일 잣대 대비 — (A)룰단독 / (B)룰+SLM / (S)선택적]")
    print(f"{'카테고리':<8} {'n_pos':>5}  {'(A)룰단독':<22} {'(B)룰+SLM':<22} {'(S)선택적':<22}")
    print("-" * 86)
    for c in CATEGORIES:
        a = A["per_cat"][c]; b = B["per_cat"][c]; s = S["per_cat"][c]
        print(f"{c:<8} {a['n_pos']:>5}  {_fmt(a):<22} {_fmt(b):<22} {_fmt(s):<22}")
    print("-" * 86)
    print(f"{'TOTAL':<8} {A['total']['n_pos']:>5}  "
          f"{_fmt(A['total']):<22} {_fmt(B['total']):<22} {_fmt(S['total']):<22}")

    # ── 동일 잣대 비교표 (in-process 재산출 + 팀장 확정값 병기) ──
    st = S["total"]
    print("\n[동일 잣대 비교표 — TOTAL micro-F1]  (재산출 = 본 실행 계산값)")
    print(f"{'방법':<22} {'재산출':<24} {'팀장확정':<22}")
    print("-" * 70)
    print(f"{'룰단독':<22} {_fmt(A['total']):<24} {'0.495 [0.457,0.530]':<22}")
    print(f"{'순수MLP':<22} {'(미산출, 학습모델)':<24} {'0.508':<22}")
    print(f"{'룰+SLM 앙상블(최고)':<20} {_fmt(B['total']):<24} {'0.537 [0.505,0.574]':<22}")
    print(f"{'선택적 앙상블(S)':<20} {_fmt(st):<24} {'(신규)':<22}")

    # ── 핵심 판정: 재산출한 앙상블 baseline 대비 (자기검증) ──
    ens_pt, ens_lo, ens_hi = B["total"]["f1"], B["total"]["ci_lo"], B["total"]["ci_hi"]
    print("\n[핵심 판정]  (재산출 앙상블 baseline 기준)")
    print(f"  선택적 점추정 {st['f1']:.3f}  vs  앙상블 점추정 {ens_pt:.3f}")
    if st["f1"] > ens_pt:
        print(f"  → 점추정으로 앙상블 초과 (+{st['f1']-ens_pt:.3f})")
    elif st["f1"] == ens_pt:
        print("  → 점추정 동일")
    else:
        print(f"  → 점추정으로 앙상블 미달 ({st['f1']-ens_pt:+.3f})")
    overlap = not (st["ci_hi"] < ens_lo or st["ci_lo"] > ens_hi)
    print(f"  선택적 CI [{st['ci_lo']:.3f},{st['ci_hi']:.3f}]  vs  앙상블 CI [{ens_lo:.3f},{ens_hi:.3f}]")
    print(f"  → CI 겹침: {'예 (유의하지 않음)' if overlap else '아니오 (유의)'}")

    out = dict(selective=S, rule_only=A, rule_slm=B, n=len(keys),
               verdict=dict(selective_point=st["f1"],
                            selective_ci=[st["ci_lo"], st["ci_hi"]],
                            ensemble_point=ens_pt, ensemble_ci=[ens_lo, ens_hi],
                            point_beats=bool(st["f1"] > ens_pt),
                            ci_overlap=bool(overlap)),
               baselines_teamlead=dict(rule_only="0.495 [0.457,0.530]",
                                       pure_mlp="0.508",
                                       rule_slm="0.537 [0.505,0.574]"))
    Path("outputs/selective_ensemble_measure.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n(측정 산출물 outputs/selective_ensemble_measure.json 기록 — 프로덕션 미수정)")


if __name__ == "__main__":
    main()
