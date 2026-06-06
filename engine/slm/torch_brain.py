"""Phase 3 — PyTorch 본격 신경망.

Embedding (ArticleType, Subject, Modal) + Dense (정량 신호) → MLP →
Multi-task output (5 카테고리 simultaneous).

조건: torch 가용시만 작동.
"""
from __future__ import annotations

import json
import pickle
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import TensorDataset, DataLoader
    _TORCH_OK = True
except ImportError:
    _TORCH_OK = False
    torch = None  # type: ignore

    class _NNStub:  # torch 미설치 시 클래스 정의만 통과시키는 스텁
        Module = object

    nn = _NNStub()  # type: ignore
    TensorDataset = DataLoader = None  # type: ignore

from ..parser import parse_law
from ..structure import decompose, ArticleType, Subject, Modal
from .brain import CATEGORIES
from .features import extract_features, FEATURE_NAMES
from .learn import RULE_CAT, REASONING_RULE_CAT


# 범주 인덱싱
_AT_LIST = list(ArticleType)
_SUBJ_LIST = list(Subject)
_MODAL_LIST = list(Modal)
_AT_IDX = {t: i for i, t in enumerate(_AT_LIST)}
_SUBJ_IDX = {s: i for i, s in enumerate(_SUBJ_LIST)}
_MODAL_IDX = {m: i for i, m in enumerate(_MODAL_LIST)}


class TorchBrain(nn.Module):
    """Embedding + Dense + Multi-layer NN multi-task."""

    def __init__(
        self,
        n_dense: int,
        n_categories: int = 5,
        type_emb: int = 4,
        subj_emb: int = 3,
        modal_emb: int = 3,
        hidden: tuple[int, ...] = (32, 16),
        dropout: float = 0.2,
    ):
        super().__init__()
        self.emb_type = nn.Embedding(len(_AT_LIST), type_emb)
        self.emb_subj = nn.Embedding(len(_SUBJ_LIST), subj_emb)
        self.emb_modal = nn.Embedding(len(_MODAL_LIST), modal_emb)
        input_dim = n_dense + type_emb + subj_emb + modal_emb
        layers = []
        prev = input_dim
        for h in hidden:
            layers.append(nn.Linear(prev, h))
            layers.append(nn.ReLU())
            layers.append(nn.Dropout(dropout))
            prev = h
        layers.append(nn.Linear(prev, n_categories))
        self.mlp = nn.Sequential(*layers)

    def forward(self, dense, type_idx, subj_idx, modal_idx):
        e1 = self.emb_type(type_idx)
        e2 = self.emb_subj(subj_idx)
        e3 = self.emb_modal(modal_idx)
        x = torch.cat([dense, e1, e2, e3], dim=-1)
        return torch.sigmoid(self.mlp(x))


def _extract_dense_and_cat(art, *, law=None, feature_names=None):
    """Article → (dense_vec, type_idx, subj_idx, modal_idx).

    feature_names 지정시 해당 순서로 dense 추출 (모델 버전 호환).
    None 이면 FEATURE_NAMES 전체 사용.
    """
    from .features import FEATURE_NAMES as _FN
    decomp = decompose(art)
    fv = extract_features(art, decomp, law=law)

    names = feature_names if feature_names is not None else _FN
    dense = fv.to_array(names)

    type_idx = _AT_IDX[decomp.type]
    subj_idx = _SUBJ_IDX[decomp.primary_subject]
    first_modal = Modal.NONE
    for p in decomp.paragraphs:
        if p.modal != Modal.NONE:
            first_modal = p.modal
            break
    modal_idx = _MODAL_IDX[first_modal]
    return dense, type_idx, subj_idx, modal_idx


def collect_torch_data():
    """verdict 데이터 → numpy arrays (dense + cat indices + multi-task labels).

    numpy만 사용 → torch 미설치 환경에서도 적재 검증 가능(학습은 train_torch에서 torch 필요).
    """
    with open("outputs/verification_dataset.jsonl") as f:
        rows = [json.loads(l) for l in f]
    fid_map = json.loads(Path("outputs/fid_article_map.json").read_text(encoding="utf-8"))

    # article 별로 grouping — 5 카테고리 multi-label 동시
    art_labels: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    art_objects: dict[tuple[str, str], Any] = {}

    law_cache: dict[str, Any] = {}

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
        # 패턴코드(S-*) 우선, 없으면 추론룰(R-*) 보조맵 — phase13 verdict 라벨 적재용.
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
        art_objects[key] = art
        # 둘 다 라벨 있으면 OR (TP 우선)
        label = 1 if r["verdict"] == "TP" else 0
        prev = art_labels[key].get(cat)
        if prev is None or label > prev:
            art_labels[key][cat] = label

    # tensor 화
    dense_list = []
    type_list = []
    subj_list = []
    modal_list = []
    y_list = []
    for key, art in art_objects.items():
        dense, ti, si, mi = _extract_dense_and_cat(art)
        dense_list.append(dense)
        type_list.append(ti)
        subj_list.append(si)
        modal_list.append(mi)
        # multi-task label: 5 카테고리, missing 은 -1 (loss masking)
        labels = [art_labels[key].get(c, -1) for c in CATEGORIES]
        y_list.append(labels)

    dense_arr = np.array(dense_list, dtype=np.float32)
    type_arr = np.array(type_list, dtype=np.int64)
    subj_arr = np.array(subj_list, dtype=np.int64)
    modal_arr = np.array(modal_list, dtype=np.int64)
    y_arr = np.array(y_list, dtype=np.float32)

    return dense_arr, type_arr, subj_arr, modal_arr, y_arr


def _fit_eval_once(
    dense, ti, si, mi, y, train_idx, test_idx,
    *,
    hidden: tuple[int, ...] = (32, 16),
    dropout: float = 0.2,
    epochs: int = 100,
    lr: float = 1e-3,
    batch_size: int = 32,
):
    """단일 split 의 scaler→fit→eval 코어 (train_torch / evaluate_cv 공용).

    반환:
        model   : 학습된 TorchBrain (임시; 저장은 호출자 책임)
        scaler  : fit 된 StandardScaler
        pred_te : (n_test, n_cat) 테스트 sigmoid 점수 (확률)
        y_te_np : (n_test, n_cat) 테스트 라벨 (-1=결측 마스크)
    """
    if not _TORCH_OK:
        raise RuntimeError("torch not installed")

    # 표준화 (dense) — train 으로만 fit (leakage 방지)
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler().fit(dense[train_idx])
    dense_n = scaler.transform(dense)

    device = torch.device("cpu")
    model = TorchBrain(
        n_dense=dense_n.shape[1],
        n_categories=len(CATEGORIES),
        hidden=hidden,
        dropout=dropout,
    ).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-3)

    # 데이터셋
    X_dense_tr = torch.tensor(dense_n[train_idx], dtype=torch.float32)
    X_ti_tr = torch.tensor(ti[train_idx], dtype=torch.long)
    X_si_tr = torch.tensor(si[train_idx], dtype=torch.long)
    X_mi_tr = torch.tensor(mi[train_idx], dtype=torch.long)
    y_tr = torch.tensor(y[train_idx], dtype=torch.float32)

    X_dense_te = torch.tensor(dense_n[test_idx], dtype=torch.float32)
    X_ti_te = torch.tensor(ti[test_idx], dtype=torch.long)
    X_si_te = torch.tensor(si[test_idx], dtype=torch.long)
    X_mi_te = torch.tensor(mi[test_idx], dtype=torch.long)
    y_te = torch.tensor(y[test_idx], dtype=torch.float32)

    ds = TensorDataset(X_dense_tr, X_ti_tr, X_si_tr, X_mi_tr, y_tr)
    dl = DataLoader(ds, batch_size=batch_size, shuffle=True)

    # Loss: BCE (masking -1) + 클래스 가중 (TP 희소 → pos_weight 로 recall 보강)
    bce = nn.BCELoss(reduction="none")
    # 카테고리별 양성(TP) 비율로 pos_weight 산정
    y_tr_np = y[train_idx]
    pos_w = []
    for i in range(len(CATEGORIES)):
        col = y_tr_np[:, i]
        n_pos = float((col == 1).sum())
        n_neg = float((col == 0).sum())
        pos_w.append(min(max(n_neg / max(n_pos, 1.0), 1.0), 8.0))  # 1~8 범위 클립
    pos_weight = torch.tensor(pos_w, dtype=torch.float32)

    model.train()
    for epoch in range(epochs):
        for batch in dl:
            d, t, s, m, yb = batch
            opt.zero_grad()
            pred = model(d, t, s, m)
            mask = (yb >= 0).float()
            yb_masked = torch.clamp(yb, 0.0, 1.0)
            # 양성 샘플에 pos_weight 적용 (recall 보강)
            w = 1.0 + yb_masked * (pos_weight - 1.0)
            loss = (bce(pred, yb_masked) * w * mask).sum() / max(mask.sum().item(), 1)
            loss.backward()
            opt.step()

    # 평가
    model.eval()
    with torch.no_grad():
        pred_te = model(X_dense_te, X_ti_te, X_si_te, X_mi_te).numpy()
    y_te_np = y_te.numpy()
    return model, scaler, pred_te, y_te_np


def _counts_from_preds(pred_te, y_te_np):
    """(pred 확률, 라벨) → per-cat TP/FP/FN/TN dict (임계값 0.5)."""
    per_cat = {}
    for i, cat in enumerate(CATEGORIES):
        y_true = y_te_np[:, i]
        y_pred = (pred_te[:, i] >= 0.5).astype(float)
        mask = (y_true >= 0)
        yt = y_true[mask]; yp = y_pred[mask]
        tp = int(((yp == 1) & (yt == 1)).sum())
        fp = int(((yp == 1) & (yt == 0)).sum())
        fn = int(((yp == 0) & (yt == 1)).sum())
        tn = int(((yp == 0) & (yt == 0)).sum())
        per_cat[cat] = dict(tp=tp, fp=fp, fn=fn, tn=tn)
    return per_cat


def _prf(tp, fp, fn):
    p = tp / max(tp + fp, 1)
    r = tp / max(tp + fn, 1)
    f1 = 2 * p * r / max(p + r, 1e-9)
    return p, r, f1


def train_torch(
    hidden: tuple[int, ...] = (32, 16),
    dropout: float = 0.2,
    epochs: int = 100,
    lr: float = 1e-3,
    batch_size: int = 32,
    test_size: float = 0.2,
):
    """PyTorch multi-task NN 학습 (단일 split — 프로덕션 모델 저장)."""
    if not _TORCH_OK:
        raise RuntimeError("torch not installed")
    dense, ti, si, mi, y = collect_torch_data()
    n = dense.shape[0]
    # train/test split
    rng = np.random.default_rng(42)
    perm = rng.permutation(n)
    n_test = int(n * test_size)
    test_idx = perm[:n_test]
    train_idx = perm[n_test:]

    model, scaler, pred_te, y_te_np = _fit_eval_once(
        dense, ti, si, mi, y, train_idx, test_idx,
        hidden=hidden, dropout=dropout, epochs=epochs, lr=lr, batch_size=batch_size,
    )
    dense_n_dim = dense.shape[1]

    print(f"\n{'카테고리':<10} {'TP':>4} {'FP':>4} {'FN':>4} {'TN':>4} {'P':>6} {'R':>6} {'F1':>6}")
    print("-" * 60)
    counts = _counts_from_preds(pred_te, y_te_np)
    per_cat = {}
    for cat in CATEGORIES:
        c = counts[cat]
        p, r, f1 = _prf(c["tp"], c["fp"], c["fn"])
        per_cat[cat] = dict(**c, p=p, r=r, f1=f1)
        print(f"{cat:<10} {c['tp']:>4} {c['fp']:>4} {c['fn']:>4} {c['tn']:>4} {p:>6.3f} {r:>6.3f} {f1:>6.3f}")

    total = {k: sum(d[k] for d in per_cat.values()) for k in ("tp", "fp", "fn", "tn")}
    p, r, f1 = _prf(total["tp"], total["fp"], total["fn"])
    print("-" * 60)
    print(f"{'TOTAL':<10} {total['tp']:>4} {total['fp']:>4} {total['fn']:>4} {total['tn']:>4} "
          f"{p:>6.3f} {r:>6.3f} {f1:>6.3f}")

    # 모델 저장 (feature_names 포함 — 추론 시 차원 정합성 보장)
    torch.save({
        "model_state": model.state_dict(),
        "n_dense": dense_n_dim,
        "hidden": list(hidden),
        "dropout": dropout,
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(),
        "feature_names": list(FEATURE_NAMES),
    }, "outputs/slm_torch_model.pt")
    return per_cat, total


def evaluate_cv(
    k: int = 5,
    seed: int = 42,
    n_boot: int = 1000,
    n_pos_min: int = 15,
    *,
    hidden: tuple[int, ...] = (32, 16),
    dropout: float = 0.2,
    epochs: int = 100,
    lr: float = 1e-3,
    batch_size: int = 32,
):
    """Stratified K-fold + bootstrap 95% CI 로 F1 신뢰도 평가.

    단일 20% split 1회 대신 K-fold 로 전 표본을 test 에 한 번씩 노출하고,
    fold 별 test 예측을 합쳐(out-of-fold) bootstrap 으로 F1 95% CI 를 추정한다.

    Stratify: 5 카테고리 multi-label 이라 진짜 stratify 가 어려워,
    '행이 TP(양성=1) 라벨을 하나라도 보유하는지'를 단일 이진 기준으로
    근사 stratify 한다(StratifiedKFold). → 희소한 양성 행이 각 fold test 에
    고르게 분포하도록 보장. 양성 보유 행 < k 이면 단순 KFold 로 폴백.

    프로덕션 모델(outputs/slm_torch_model.pt)은 저장하지 않는다(임시 모델만 사용).
    """
    if not _TORCH_OK:
        raise RuntimeError("torch not installed")
    from sklearn.model_selection import StratifiedKFold, KFold

    dense, ti, si, mi, y = collect_torch_data()
    n = dense.shape[0]

    # 근사 stratify 키: 행에 양성(==1) 라벨이 하나라도 있으면 1
    strat = ((y == 1).any(axis=1)).astype(int)
    n_pos_rows = int(strat.sum())
    if n_pos_rows >= k and n_pos_rows <= n - k:
        splitter = StratifiedKFold(n_splits=k, shuffle=True, random_state=seed)
        split_iter = splitter.split(np.zeros(n), strat)
        strat_mode = f"StratifiedKFold(양성보유행 {n_pos_rows}/{n} 기준 근사)"
    else:
        splitter = KFold(n_splits=k, shuffle=True, random_state=seed)
        split_iter = splitter.split(np.zeros(n))
        strat_mode = f"KFold(양성보유행 {n_pos_rows} 부족 → 단순 분할 폴백)"

    # out-of-fold: 각 행이 test 였을 때의 (예측확률, 라벨) 누적
    oof_pred = np.full((n, len(CATEGORIES)), np.nan, dtype=np.float32)
    oof_y = np.full((n, len(CATEGORIES)), -1.0, dtype=np.float32)
    fold_counts = []  # fold 별 per-cat counts (참고용)

    print(f"[CV] {strat_mode}, k={k}, seed={seed}, n_boot={n_boot}, N={n}")
    for fold_i, (train_idx, test_idx) in enumerate(split_iter):
        _, _, pred_te, y_te_np = _fit_eval_once(
            dense, ti, si, mi, y, train_idx, test_idx,
            hidden=hidden, dropout=dropout, epochs=epochs, lr=lr, batch_size=batch_size,
        )
        oof_pred[test_idx] = pred_te
        oof_y[test_idx] = y_te_np
        fold_counts.append(_counts_from_preds(pred_te, y_te_np))
        c = _counts_from_preds(pred_te, y_te_np)
        tot = {kk: sum(d[kk] for d in c.values()) for kk in ("tp", "fp", "fn", "tn")}
        _, _, f1 = _prf(tot["tp"], tot["fp"], tot["fn"])
        print(f"  fold {fold_i}: test n={len(test_idx)}  TOTAL F1={f1:.3f}")

    # ── 점추정(전체 OOF) + bootstrap CI ──
    rng = np.random.default_rng(seed)

    def f1_from_indices(idx, col):
        """주어진 행 idx, 카테고리 col 에 대한 F1 (마스크 결측 제외)."""
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
        """bootstrap (행 단위 resample) 95% CI."""
        stats = np.empty(n_boot, dtype=np.float64)
        for b in range(n_boot):
            samp = rng.integers(0, n, size=n)
            stats[b] = point_fn(samp)
        lo, hi = np.percentile(stats, [2.5, 97.5])
        return float(lo), float(hi)

    print(f"\n{'카테고리':<10} {'n_pos':>6} {'F1':>7} {'95%CI_lo':>9} {'95%CI_hi':>9}  플래그")
    print("-" * 60)
    per_cat = {}
    for ci, cat in enumerate(CATEGORIES):
        # test 양성 표본 수 (OOF 전체에서 라벨==1)
        n_pos = int((oof_y[:, ci] == 1).sum())
        f1_point = f1_from_indices(all_idx, ci)
        if n_pos < n_pos_min:
            flag = "측정불가"
            lo = hi = float("nan")
        else:
            flag = ""
            lo, hi = boot_ci(lambda idx, _c=ci: f1_from_indices(idx, _c))
        per_cat[cat] = dict(n_pos=n_pos, f1=f1_point, ci_lo=lo, ci_hi=hi,
                            measurable=(n_pos >= n_pos_min))
        ci_lo_s = f"{lo:>9.3f}" if n_pos >= n_pos_min else f"{'-':>9}"
        ci_hi_s = f"{hi:>9.3f}" if n_pos >= n_pos_min else f"{'-':>9}"
        print(f"{cat:<10} {n_pos:>6} {f1_point:>7.3f} {ci_lo_s} {ci_hi_s}  {flag}")

    total_n_pos = int((oof_y == 1).sum())
    total_f1 = f1_total_from_indices(all_idx)
    total_lo, total_hi = boot_ci(f1_total_from_indices)
    total = dict(n_pos=total_n_pos, f1=total_f1, ci_lo=total_lo, ci_hi=total_hi)
    print("-" * 60)
    print(f"{'TOTAL':<10} {total_n_pos:>6} {total_f1:>7.3f} {total_lo:>9.3f} {total_hi:>9.3f}")

    return dict(per_cat=per_cat, total=total, strat_mode=strat_mode,
                k=k, seed=seed, n_boot=n_boot, n=n)


# ────────── 추론 API ──────────

_MODEL_CACHE: dict = {}


def _load_model_cache() -> dict | None:
    """slm_torch_model.pt 로드 (프로세스 내 캐시)."""
    if _MODEL_CACHE:
        return _MODEL_CACHE
    model_path = Path("outputs/slm_torch_model.pt")
    if not model_path.exists():
        return None
    try:
        ck = torch.load(model_path, map_location="cpu", weights_only=False)
        feature_names = ck.get("feature_names", list(FEATURE_NAMES))
        n_dense = ck["n_dense"]
        model = TorchBrain(
            n_dense=n_dense,
            n_categories=len(CATEGORIES),
            hidden=tuple(ck["hidden"]),
            dropout=ck.get("dropout", 0.2),
        )
        model.load_state_dict(ck["model_state"])
        model.eval()
        _MODEL_CACHE.update({
            "model": model,
            "feature_names": feature_names,
            "n_dense": n_dense,
            "scaler_mean": np.array(ck["scaler_mean"], dtype=np.float32),
            "scaler_scale": np.array(ck["scaler_scale"], dtype=np.float32),
        })
        return _MODEL_CACHE
    except Exception:
        return None


def torch_infer_article(art, *, law=None):
    """TorchBrain 으로 단일 조문 5카테고리 진단.

    모델 파일 없거나 차원 불일치 시 None 반환 → 호출자가 linear brain 으로 fallback.
    """
    if not _TORCH_OK:
        return None
    cache = _load_model_cache()
    if cache is None:
        return None

    feature_names = cache["feature_names"]
    n_dense = cache["n_dense"]

    dense, ti, si, mi = _extract_dense_and_cat(art, law=law, feature_names=feature_names)
    if len(dense) != n_dense:
        return None

    scaler_mean = cache["scaler_mean"]
    scaler_scale = cache["scaler_scale"]
    dense_n = (np.array(dense, dtype=np.float32) - scaler_mean) / (scaler_scale + 1e-8)

    model = cache["model"]
    d_t = torch.tensor(dense_n, dtype=torch.float32).unsqueeze(0)
    ti_t = torch.tensor([ti], dtype=torch.long)
    si_t = torch.tensor([si], dtype=torch.long)
    mi_t = torch.tensor([mi], dtype=torch.long)

    with torch.no_grad():
        scores = model(d_t, ti_t, si_t, mi_t).squeeze(0).numpy()

    from .brain import CategoryDiagnosis, _classify_severity
    result = {}
    for i, cat in enumerate(CATEGORIES):
        score = float(scores[i])
        result[cat] = CategoryDiagnosis(
            category=cat,
            article_number=art.number,
            article_title=art.title or "",
            score=score,
            severity=_classify_severity(score),
            confidence=min(1.0, abs(score - 0.5) * 2),
            contributing_signals=[],
        )
    return result
